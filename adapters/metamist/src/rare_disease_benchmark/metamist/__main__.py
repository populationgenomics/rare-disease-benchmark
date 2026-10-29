"""The adapter's commands, `ingest`, `sample-sheet` and `register`; `--help` on each describes it."""

from __future__ import annotations

import argparse
import pathlib
from collections.abc import Sequence

from rare_disease_benchmark.metamist import client, ingest, pedigree, records, register, sample_sheet, storage


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog='python -m rare_disease_benchmark.metamist',
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest='command', required=True)

    ingest_parser = commands.add_parser(
        'ingest',
        help='copy participants, as one family, from one project into another',
        description=ingest.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ingest_parser.add_argument('--source', required=True, help='the project to copy from')
    ingest_parser.add_argument('--target', required=True, help='the project to copy into')
    ingest_parser.add_argument('--family', required=True, help="the family's external id in the target")
    ingest_parser.add_argument(
        '--cram-template',
        required=True,
        type=ingest.check_cram_template,
        help="the URL of a source sequencing group's CRAM, with {sequencing_group} for its id; the CRAI is beside it",
    )
    ingest_parser.add_argument(
        '--ped', type=pathlib.Path, help="a PED file with the members' sex and parents; without it, the source's"
    )
    ingest_parser.add_argument('--dry-run', action='store_true', help='print the writes instead of making them')
    ingest_parser.add_argument('ids', nargs='+', metavar='external_id', help="the members' external ids in the source")

    sheet_parser = commands.add_parser(
        'sample-sheet',
        help="write the build pipeline's sample sheet for a family",
        description=sample_sheet.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sheet_parser.add_argument('--project', required=True, help='the project that holds the family')
    sheet_parser.add_argument('--family', required=True, help="the family's external id")
    sheet_parser.add_argument('--output', required=True, help='where to write the CSV: a local path or a gs:// URL')

    register_parser = commands.add_parser(
        'register',
        help="register a build run's outputs as analyses",
        description=register.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    register_parser.add_argument('directory', help="the run's manifest directory, local or gs://")
    register_parser.add_argument('--project', required=True, help='the project holding the sequencing groups')
    register_parser.add_argument('--pipeline-version', required=True, help='the pipeline version that wrote the run')
    register_parser.add_argument('--dry-run', action='store_true', help='print the requests instead of sending them')

    args = parser.parse_args(argv)
    try:
        if args.command == 'ingest':
            _ingest(args)
        elif args.command == 'sample-sheet':
            _sample_sheet(args)
        else:
            _register(args)
    except records.RecordError as error:
        raise SystemExit(f'error: {error}') from error


def _ingest(args: argparse.Namespace) -> None:
    ped = None if args.ped is None else pedigree.read_ped(args.ped.read_text(encoding='utf-8'), args.ids, str(args.ped))
    plan = ingest.plan(
        client.MetamistRegistry(),
        storage.CloudStorage(),
        source=args.source,
        target=args.target,
        family=args.family,
        ids=args.ids,
        cram_template=args.cram_template,
        ped=ped,
    )
    if not plan.create and not plan.pedigree:
        print(f'{args.target} already holds {", ".join(args.ids)} as the family {args.family}; nothing to write')
        return
    ingest.apply(plan, client.DryRunWriter() if args.dry_run else client.MetamistWriter())
    if not args.dry_run:
        print(
            f'{args.target}: created {len(plan.create)} participants, '
            f'{"imported" if plan.pedigree else "kept"} the pedigree of {args.family}'
        )


def _sample_sheet(args: argparse.Namespace) -> None:
    text = sample_sheet.to_csv(sample_sheet.rows(client.MetamistRegistry(), args.project, args.family))
    storage.CloudStorage().write_text(args.output, text)


def _register(args: argparse.Namespace) -> None:
    register.register(
        args.directory,
        args.project,
        args.pipeline_version,
        storage=storage.CloudStorage(),
        reader=register.GraphQLReader(),
        writer=register.DryRunWriter() if args.dry_run else register.ApiWriter(),
    )


if __name__ == '__main__':
    main()
