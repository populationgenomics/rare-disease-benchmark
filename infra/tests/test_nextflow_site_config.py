from __future__ import annotations

import ast
import pathlib

import nextflow_site_config
import pytest

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


def _exported_names() -> set[str]:
    program = pathlib.Path(nextflow_site_config.__file__).with_name('__main__.py')
    return {
        node.args[0].value
        for node in ast.walk(ast.parse(program.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'export'
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def test_the_program_exports_every_required_output() -> None:
    assert set(nextflow_site_config.REQUIRED_OUTPUTS) <= _exported_names()


def test_render_places_each_output() -> None:
    config = nextflow_site_config.render(OUTPUTS, stack='example', dragen_image_tag='4.6.2')
    for value in OUTPUTS.values():
        if value != OUTPUTS['dataBucket']:
            assert f"'{value}" in config, value
    assert f"container = '{OUTPUTS['imagePrefix']}/dragen:4.6.2'" in config
    assert f"dragen_reference = '{OUTPUTS['dataBucket']}/{nextflow_site_config.DRAGEN_REFERENCE}'" in config


def test_render_rejects_a_missing_output() -> None:
    outputs = {key: value for key, value in OUTPUTS.items() if key != 'network'}
    with pytest.raises(ValueError, match='network'):
        nextflow_site_config.render(outputs, stack='example', dragen_image_tag='4.6.2')


@pytest.mark.parametrize('tag', ['', 'latest:1', '4.6 2', '-4.6'])
def test_render_rejects_a_malformed_tag(tag: str) -> None:
    with pytest.raises(ValueError, match='not a valid image tag'):
        nextflow_site_config.render(OUTPUTS, stack='example', dragen_image_tag=tag)


def test_render_refuses_a_value_needing_escapes() -> None:
    outputs = OUTPUTS | {'network': "projects/x'/networks/pipeline"}
    with pytest.raises(ValueError, match='refusing'):
        nextflow_site_config.render(outputs, stack='example', dragen_image_tag='4.6.2')
