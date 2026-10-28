from __future__ import annotations

import ast
import pathlib
import re

import pipeline_config
import pytest
import references

# Invented outputs, in the form the program exports them.
OUTPUTS = {
    'project': 'example-project',
    'region': 'australia-southeast1',
    'workDir': 'gs://example-project-work/work',
    'outputDir': 'gs://example-project-data/results',
    'dataBucket': 'gs://example-project-data',
    'network': 'projects/example-project/global/networks/pipeline',
    'subnetwork': 'projects/example-project/regions/australia-southeast1/subnetworks/pipeline',
    'serviceAccountEmail': 'pipeline-tasks@example-project.iam.gserviceaccount.com',
    'imagePrefix': 'australia-southeast1-docker.pkg.dev/example-project/images',
    'dragenApiKeySecret': 'projects/example-project/secrets/dragen-api-key/versions/latest',
}

_BUILD = pathlib.Path(pipeline_config.__file__).parents[1] / 'build'


def _exported_names() -> set[str]:
    program = pathlib.Path(pipeline_config.__file__).with_name('__main__.py')
    return {
        node.args[0].value
        for node in ast.walk(ast.parse(program.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'export'
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _declared_params() -> set[str]:
    block = re.search(r'^params \{\n(.*?)^\}', (_BUILD / 'main.nf').read_text(), re.S | re.M)
    assert block
    return set(re.findall(r'^\s+(\w+):', block.group(1), re.M))


def test_the_program_exports_every_output_used() -> None:
    assert {*pipeline_config.PARAMS_OUTPUTS, *pipeline_config.SITE_OUTPUTS} <= _exported_names()


def test_every_param_written_is_declared_by_the_pipeline() -> None:
    written = pipeline_config.params(OUTPUTS, stack='example', dragen_image_tag='4.6.2')
    assert set(written) <= _declared_params()


def test_params_point_at_the_references_and_the_image() -> None:
    written = pipeline_config.params(OUTPUTS, stack='example', dragen_image_tag='4.6.2')
    assert written['dragen_reference'] == f'{OUTPUTS["dataBucket"]}/{references.DRAGEN_REFERENCE}'
    assert written['cram_reference'] == f'{OUTPUTS["dataBucket"]}/{references.CRAM_REFERENCE}'
    assert written['dragen_container'] == f'{OUTPUTS["imagePrefix"]}/dragen:4.6.2'


def test_site_config_places_each_output() -> None:
    config = pipeline_config.site_config(OUTPUTS, stack='example')
    for key in pipeline_config.SITE_OUTPUTS:
        assert f"'{OUTPUTS[key]}'" in config, key


def test_a_missing_output_is_named() -> None:
    outputs = {key: value for key, value in OUTPUTS.items() if key != 'network'}
    with pytest.raises(ValueError, match='network'):
        pipeline_config.site_config(outputs, stack='example')


@pytest.mark.parametrize('tag', ['', 'latest:1', '4.6 2', '-4.6'])
def test_a_malformed_tag_is_refused(tag: str) -> None:
    with pytest.raises(ValueError, match='not a valid image tag'):
        pipeline_config.params(OUTPUTS, stack='example', dragen_image_tag=tag)


def test_a_value_needing_escapes_is_refused() -> None:
    outputs = OUTPUTS | {'network': "projects/x'/networks/pipeline"}
    with pytest.raises(ValueError, match='refusing'):
        pipeline_config.site_config(outputs, stack='example')
