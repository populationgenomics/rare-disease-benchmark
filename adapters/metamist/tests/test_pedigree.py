from __future__ import annotations

import pytest

from rare_disease_benchmark.metamist import pedigree, records

from . import fakes

# Invented rows in the two layouts of the public 1000 Genomes pedigrees: tab-separated with a header of spaced names and
# extra columns, and space-separated with a header and population columns in place of the phenotype.
TAB_SEPARATED = (
    'Family ID\tIndividual ID\tPaternal ID\tMaternal ID\tGender\tPhenotype\tPopulation\n'
    f'fam_x\t{fakes.MOTHER}\t0\t0\t2\t0\tPOP\n'
    f'fam_x\t{fakes.FATHER}\t0\t0\t1\t0\tPOP\n'
    f'fam_x\t{fakes.CHILD}\t{fakes.FATHER}\t{fakes.MOTHER}\t2\t0\tPOP\n'
    f'fam_y\tother_1\t0\t{fakes.MOTHER}\t1\t0\tPOP\n'
)
SPACE_SEPARATED = (
    'FamilyID SampleID FatherID MotherID Sex Population Superpopulation\n'
    f'fam_x {fakes.MOTHER} 0 0 2 POP SUPER\n'
    f'fam_x {fakes.FATHER} 0 0 1 POP SUPER\n'
    f'fam_x {fakes.CHILD} {fakes.FATHER} {fakes.MOTHER} 2 POP SUPER\n'
)


def member(member_id: str, sex: records.Sex, father: str | None = None, mother: str | None = None) -> records.Member:
    return records.Member(id=member_id, sex=sex, father=father, mother=mother)


TRIO = (
    member(fakes.MOTHER, 'female'),
    member(fakes.FATHER, 'male'),
    member(fakes.CHILD, 'female', fakes.FATHER, fakes.MOTHER),
)


@pytest.mark.parametrize('text', [TAB_SEPARATED, SPACE_SEPARATED], ids=['tabs', 'spaces'])
def test_both_public_layouts_read_the_same_members(text: str) -> None:
    assert pedigree.read_ped(text, fakes.TRIO, 'ped') == {m.id: m for m in TRIO}


def test_rows_of_others_are_ignored_even_when_they_name_a_member() -> None:
    assert pedigree.read_ped(TAB_SEPARATED, [fakes.MOTHER], 'ped') == {fakes.MOTHER: TRIO[0]}


@pytest.mark.parametrize(
    ('text', 'message'),
    [
        (SPACE_SEPARATED.replace(f'fam_x {fakes.CHILD}', f'fam_x {fakes.CHILD}_other'), f'0 rows for {fakes.CHILD},'),
        (SPACE_SEPARATED + f'fam_z {fakes.CHILD} 0 0 2\n', f'2 rows for {fakes.CHILD}'),
        (SPACE_SEPARATED.replace(f'{fakes.MOTHER} 0 0 2', f'{fakes.MOTHER} 0 0 0'), "sex '0'"),
        (SPACE_SEPARATED.replace(f'{fakes.MOTHER} 0 0 2 POP SUPER', f'{fakes.MOTHER} 0 0'), 'has 4 columns'),
    ],
    ids=['missing', 'repeated', 'unknown sex', 'short row'],
)
def test_a_member_must_have_one_complete_row_with_a_known_sex(text: str, message: str) -> None:
    with pytest.raises(records.RecordError, match=message):
        pedigree.read_ped(text, fakes.TRIO, 'ped')


def test_a_whole_trio_is_a_family() -> None:
    pedigree.check_family(TRIO, 'fam')


@pytest.mark.parametrize(
    ('members', 'message'),
    [
        ((*TRIO, TRIO[0]), 'appears twice'),
        ((TRIO[0], TRIO[2]), f'the father of {fakes.CHILD}, {fakes.FATHER}, is not in the family'),
        ((member('a', 'female', 'b'), member('b', 'female')), 'b is the father of a but female'),
        ((member('a', 'male', mother='b'), member('b', 'male')), 'b is the mother of a but male'),
        ((member('a', 'male', 'a'),), 'a descend from themselves'),
        ((member('a', 'male', 'b'), member('b', 'male', 'a')), 'a, b descend from themselves'),
    ],
    ids=['repeated', 'parent outside', 'female father', 'male mother', 'own father', 'cycle'],
)
def test_a_family_with_a_parent_outside_of_the_wrong_sex_or_in_a_cycle_is_refused(
    members: tuple[records.Member, ...], message: str
) -> None:
    with pytest.raises(records.RecordError, match=message):
        pedigree.check_family(members, 'fam')
