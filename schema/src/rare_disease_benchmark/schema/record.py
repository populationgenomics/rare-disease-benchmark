"""The case record: what a curator writes for one solved case.

A case names no background and holds no sequencing data, so it can be built into any background whose structure fits,
as often as needed. It has two parts, and the split is the blinding boundary:

- `family`: the pedigree, with each member's clinical presentation. It is open: a system under test receives it as it
  stands, and its member ids are the sample names in the released files.
- `answer`: the placements and the diagnoses, which the grader compares a submission against.

The remaining fields are bookkeeping and stay withheld, like `answer`.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
from collections.abc import Iterator
from typing import Literal, Self

import pydantic

from rare_disease_benchmark.schema import ids, variant, visibility

type Sex = Literal['male', 'female', 'unknown']
type Provenance = Literal['real', 'derived', 'invented']
type Sharing = Literal['internal', 'partners', 'public']

_HPO_ID = re.compile(r'HP:\d{7}')

# Relational labels such as proband, father, half_sister or sister_2. Member ids become the sample names in released
# files, so the form keeps out accessions and other identifiers a source may use.
_MEMBER_ID = re.compile(r'[a-z]+(_[a-z]+)*(_[0-9]+)?')


# ---- open: the family ----


class ClinicalPresentation(visibility.OpenModel, frozen=True):
    """What the laboratory had for one member, at the level of detail the source holds."""

    hpo_present: tuple[str, ...] = ()  # HPO ids
    hpo_excluded: tuple[str, ...] = ()  # HPO ids
    onset: str | None = None  # an HPO onset term or the source's wording. None: not recorded
    age: str | None = None  # age or age bracket at referral. None: not recorded
    panel: str | None = None  # the panel requested. None: none or not recorded
    reason_for_referral: str | None = None  # None: not recorded
    text: str | None = None  # referral letter, clinic notes or report text, de-identified. None: no free text

    @pydantic.field_validator('hpo_present', 'hpo_excluded')
    @classmethod
    def _hpo_ids(cls, terms: tuple[str, ...]) -> tuple[str, ...]:
        for term in terms:
            if not _HPO_ID.fullmatch(term):
                raise ValueError(f'{term!r} is not an HPO id of the form HP:0000000')
        if len(set(terms)) != len(terms):
            raise ValueError(f'repeated HPO ids: {terms}')
        return terms

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        if overlap := set(self.hpo_present) & set(self.hpo_excluded):
            raise ValueError(f'HPO ids both present and excluded: {sorted(overlap)}')
        return self


class Individual(visibility.OpenModel, frozen=True):
    """One PED row, with the member's clinical presentation."""

    id: ids.MemberId
    father: ids.MemberId | None = None  # None: not in the family
    mother: ids.MemberId | None = None  # None: not in the family
    sex: Sex  # unknown as PED permits, though not for the proband
    affected: bool | None = None  # None: unknown, as PED permits
    presentation: ClinicalPresentation | None = None  # None: the source holds nothing for this member

    @pydantic.field_validator('id')
    @classmethod
    def _relational_label(cls, member_id: ids.MemberId) -> ids.MemberId:
        if not _MEMBER_ID.fullmatch(member_id):
            raise ValueError(f'member id {member_id!r} is not a relational label such as proband, father or sister_2')
        return member_id


class Family(visibility.OpenModel, frozen=True):
    proband: ids.MemberId
    members: tuple[Individual, ...]

    def member(self, member_id: ids.MemberId) -> Individual:
        for individual in self.members:
            if individual.id == member_id:
                return individual
        raise KeyError(f'{member_id!r} is not a member of the family')

    def require_member(self, member_id: ids.MemberId, context: str) -> Individual:
        """`member`, raising the ValueError a validator reports rather than a KeyError."""
        if member_id not in {m.id for m in self.members}:
            raise ValueError(f'{context}: {member_id!r} is not a member of the family')
        return self.member(member_id)

    @property
    def proband_individual(self) -> Individual:
        return self.member(self.proband)

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        member_ids = [m.id for m in self.members]
        if len(set(member_ids)) != len(member_ids):
            raise ValueError(f'member ids are not unique: {member_ids}')
        self.require_member(self.proband, 'proband')
        if self.proband_individual.sex == 'unknown':
            raise ValueError('the proband needs a known sex')
        for m in self.members:
            for parent_id, role_sex in ((m.father, 'male'), (m.mother, 'female')):
                if parent_id is None:
                    continue
                parent = self.require_member(parent_id, f'parent of {m.id!r}')
                if parent.sex != role_sex:
                    raise ValueError(f'{parent.id!r} is a {role_sex} parent of {m.id!r} but has sex {parent.sex!r}')
        for m in self.members:
            if m.id in self._ancestors(m.id):
                raise ValueError(f'{m.id!r} is their own ancestor')
        return self

    def _ancestors(self, member_id: ids.MemberId) -> set[ids.MemberId]:
        seen: set[ids.MemberId] = set()
        stack = [member_id]
        while stack:
            m = self.member(stack.pop())
            for parent in (m.father, m.mother):
                if parent is not None and parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return seen


# ---- withheld: the answer ----


class Inheritance(enum.StrEnum):
    AD = 'AD'
    AR = 'AR'
    XLD = 'XLD'
    XLR = 'XLR'
    MT = 'MT'  # mitochondrial
    # extended as cases need it


class CausativeVariant(visibility.WithheldModel, frozen=True):
    variant: variant.Variant
    first_public_date: dt.date | None = None  # ClinVar submission or publication. None: not public when recorded


class Diagnosis(visibility.WithheldModel, frozen=True):
    disease: str  # a label, compared by the grader
    ontology_id: str | None = None  # a MONDO or OMIM id where one fits. None: no fitting term
    inheritance: Inheritance
    variants: tuple[CausativeVariant, ...] = pydantic.Field(min_length=1)
    # A compound heterozygote lists both variants; a homozygous variant is listed once, and its two placements show
    # both copies.
    association_first_public_date: dt.date | None = None
    # When the gene-disease association was first published; a case whose cutoff is not after it is a discovery case.
    # None: not known, and the case is not flagged.

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        listed = [v.variant for v in self.variants]
        if any(listed.count(v) > 1 for v in listed):
            raise ValueError(f'a causative variant is listed twice in the diagnosis of {self.disease!r}')
        return self


class CaseAnswer(visibility.WithheldModel, frozen=True):
    """What the grader compares a submission against.

    Placed variants that are not part of any diagnosis are the candidates the laboratory considered and set aside.
    """

    placements: tuple[variant.Placement, ...]  # every variant in the case, once per copy per carrier
    diagnoses: tuple[Diagnosis, ...] = pydantic.Field(min_length=1)

    @property
    def causative_variants(self) -> Iterator[CausativeVariant]:
        for diagnosis in self.diagnoses:
            yield from diagnosis.variants

    @property
    def cutoff(self) -> dt.date | None:
        """The earliest date any causative variant became public; None if none is.

        Rolling a system's resources back to before it hides every causative variant at once. The harness applies it;
        the system under test never sees it, since it is the date a causative variant became public.
        """
        dates = [v.first_public_date for v in self.causative_variants if v.first_public_date is not None]
        return min(dates, default=None)

    @property
    def set_aside(self) -> tuple[variant.Variant, ...]:
        causative = [v.variant for v in self.causative_variants]
        placed = dict.fromkeys(p.variant for p in self.placements)
        return tuple(v for v in placed if v not in causative)

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        rows = [(p.haplotype, p.variant) for p in self.placements]
        if any(rows.count(row) > 1 for row in rows):
            raise ValueError('a variant is placed twice on the same haplotype')
        return self


# ---- the record ----


class Source(visibility.WithheldModel, frozen=True):
    programme: str | None = None  # the programme the case came from. None: not from a programme
    accession: str | None = None  # the programme's own identifier for the case. None: it has none


class Case(visibility.WithheldModel, frozen=True):
    """The record of one solved case. Withheld, except `family`, which a system under test receives as it stands."""

    id: ids.CaseId
    source: Source
    provenance: Provenance
    sharing: Sharing
    notes: str | None = None  # what made the case difficult. None: nothing to say
    family: Family
    answer: CaseAnswer

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        family = self.family
        revealing = [s for s in (self.id, self.source.accession) if s is not None]
        for member in family.members:
            for s in revealing:
                if s.casefold() in member.id.casefold():
                    raise ValueError(f'member id {member.id!r} contains {s!r}, and member ids are released')
        for placement in self.answer.placements:
            _check_placement(family, placement)
        for causative in self.answer.causative_variants:
            if not any(
                p.variant == causative.variant and p.haplotype.individual == family.proband
                for p in self.answer.placements
            ):
                raise ValueError(f'causative variant {_describe(causative.variant)} is not placed in the proband')
        return self


def _describe(v: variant.Variant) -> str:
    return f'{v.chrom}:{v.pos} {v.ref}>{v.alt}'


def _check_placement(family: Family, placement: variant.Placement) -> None:
    v = placement.variant
    _check_haplotype(family, placement.haplotype, v)
    if v.origin is not None:
        _check_haplotype(family, v.origin, v)
    member = family.member(placement.haplotype.individual)
    copies = 1 if _single_copy(member, v.region) else 2
    if copies == 2 and placement.vaf is not None and placement.vaf > 0.5:
        raise ValueError(
            f'vaf {placement.vaf} on one of two copies of {_describe(v)} in {member.id!r}; '
            'a larger share is two placements'
        )


def _single_copy(member: Individual, region: variant.Region) -> bool:
    match region:
        case variant.Region.MITOCHONDRIAL | variant.Region.Y:
            return True
        case variant.Region.X:
            return member.sex == 'male'
        case variant.Region.AUTOSOMAL | variant.Region.PSEUDOAUTOSOMAL:
            return False


def _check_haplotype(family: Family, haplotype: variant.Haplotype, v: variant.Variant) -> None:
    """Reject a haplotype name that does not exist for this member at this site."""
    name = haplotype.name
    where = f'{haplotype.individual!r} {name} at {_describe(v)}'
    member = family.require_member(haplotype.individual, where)
    proband = family.proband_individual

    if name in variant.CHILD_HAPLOTYPES:
        if member.id != proband.id and (member.father if name == 'paternal' else member.mother) is None:
            raise ValueError(f'{where}: {name} names a copy by a parent who is not in the family')
    elif member.id not in (proband.father, proband.mother):
        raise ValueError(f'{where}: {name} names a copy of a parent of the proband, and {member.id!r} is not one')

    region = v.region
    if region in (variant.Region.X, variant.Region.Y) and member.sex == 'unknown':
        raise ValueError(f'{where}: a member of unknown sex has no defined copies of {v.chrom}')
    allowed = _allowed_names(member, proband, region)
    if name not in allowed:
        raise ValueError(f'{where}: this copy does not exist; expected one of {sorted(allowed)}')


def _allowed_names(member: Individual, proband: Individual, region: variant.Region) -> frozenset[variant.HaplotypeName]:
    """The haplotype names that exist for a member at a site in this region."""
    is_parent = member.id in (proband.father, proband.mother)
    if region == variant.Region.Y and member.sex != 'male':
        return frozenset()
    if not _single_copy(member, region):
        return variant.CHILD_HAPLOTYPES | (variant.PARENT_HAPLOTYPES if is_parent else frozenset())
    child, parent = _only_copy_names(member, proband, region)
    return frozenset({child, parent}) if is_parent else frozenset({child})


def _only_copy_names(
    member: Individual, proband: Individual, region: variant.Region
) -> tuple[variant.HaplotypeName, variant.HaplotypeName]:
    """The child-side and parent-side name of a member's only copy at a site in this region."""
    match region:
        case variant.Region.MITOCHONDRIAL:
            # Inherited from the mother only, and all of a mother's mtDNA is passed on.
            return 'maternal', ('transmitted' if member.id == proband.mother else 'non_transmitted')
        case variant.Region.Y:
            return 'paternal', ('transmitted' if proband.sex == 'male' else 'non_transmitted')
        case variant.Region.X:
            # A male's X comes from his mother, and a father passes his to a daughter only.
            return 'maternal', ('transmitted' if proband.sex == 'female' else 'non_transmitted')
        case variant.Region.AUTOSOMAL | variant.Region.PSEUDOAUTOSOMAL:
            raise AssertionError(f'{member.id!r} has two copies in the {region} region')
