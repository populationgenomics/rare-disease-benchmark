"""Variants, haplotypes and placements: the edit instructions of a case.

A placement puts one variant on one haplotype, that is, on one chromosome copy of one family member. Haplotypes are
named by their relation to the proband rather than by a physical chromosome, which is what lets a case be written
without reference to any background:

- The proband's two copies, and those of any member whose parents are in the family, are `paternal` and `maternal`.
- A parent's copies are named by whether the copy was passed to the proband: `transmitted` and `non_transmitted`. Which
  physical copy that is changes at each crossover; the background's phasing records where.

A member's only copy (chrM, chrY, and a male's X outside the pseudoautosomal regions) takes the same names. Which names
are valid for which member depends on the family, so those rules live with the case record.
"""

from __future__ import annotations

import enum
import re
from typing import Literal, Self

import pydantic

from rare_disease_benchmark.schema import ids, visibility

type HaplotypeName = Literal['paternal', 'maternal', 'transmitted', 'non_transmitted']

CHILD_HAPLOTYPES: frozenset[HaplotypeName] = frozenset({'paternal', 'maternal'})
PARENT_HAPLOTYPES: frozenset[HaplotypeName] = frozenset({'transmitted', 'non_transmitted'})

CHROMOSOMES = frozenset({*(f'chr{i}' for i in range(1, 23)), 'chrX', 'chrY', 'chrM'})

# GRCh38 pseudoautosomal regions, 1-based inclusive. The pinned reference masks the chrY copies, so nothing may be
# placed there.
_PAR = {
    'chrX': ((10_001, 2_781_479), (155_701_383, 156_030_895)),
    'chrY': ((10_001, 2_781_479), (56_887_903, 57_217_415)),
}

_BASES = re.compile(r'[ACGTN]+')
_SYMBOLIC = re.compile(r'<[A-Z][A-Z0-9:_]*>')
UPD = '<UPD>'


class Region(enum.StrEnum):
    """How many copies of a site a member carries, by where the site is."""

    AUTOSOMAL = 'autosomal'
    PSEUDOAUTOSOMAL = 'pseudoautosomal'  # two copies in either sex
    X = 'x'  # chrX outside the pseudoautosomal regions: two copies in a female, one in a male
    Y = 'y'  # chrY outside the pseudoautosomal regions: one copy, males only
    MITOCHONDRIAL = 'mitochondrial'  # one copy, inherited from the mother


class Haplotype(visibility.WithheldModel, frozen=True):
    """One of a member's chromosome copies, named the way every phased trio names them."""

    individual: ids.MemberId
    name: HaplotypeName


class Variant(visibility.WithheldModel, frozen=True):
    """A VCF-style record on GRCh38 with one alternate allele, left-aligned.

    Left alignment and the reference allele are checked against the reference genome by the build, not here.
    """

    chrom: str  # as in the reference: chr1 .. chr22, chrX, chrY, chrM
    pos: pydantic.PositiveInt  # 1-based, as in VCF
    ref: str
    alt: str  # explicit bases; a symbolic allele such as <DEL>, <DUP>, <INV> or <INS>; or <UPD>
    end: pydantic.PositiveInt | None = None  # symbolic alleles only: last affected base. None: explicit alternate
    origin: Haplotype | None = None  # <UPD> only: the haplotype whose alleles fill the region. None otherwise

    @property
    def symbolic(self) -> bool:
        return _SYMBOLIC.fullmatch(self.alt) is not None

    @property
    def last(self) -> int:
        """The last reference base the variant touches."""
        if self.end is not None:
            return self.end
        return self.pos + len(self.ref) - 1

    @property
    def region(self) -> Region:
        if self.chrom == 'chrM':
            return Region.MITOCHONDRIAL
        if self.chrom not in _PAR:
            return Region.AUTOSOMAL
        if self._in_par():
            return Region.PSEUDOAUTOSOMAL
        return Region.X if self.chrom == 'chrX' else Region.Y

    def _in_par(self) -> bool:
        return any(start <= self.pos and self.last <= stop for start, stop in _PAR[self.chrom])

    def _touches_par(self) -> bool:
        return any(self.pos <= stop and start <= self.last for start, stop in _PAR[self.chrom])

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        if self.chrom not in CHROMOSOMES:
            raise ValueError(f'unknown chromosome {self.chrom!r}; expected chr1..chr22, chrX, chrY or chrM')
        if not _BASES.fullmatch(self.ref):
            raise ValueError(f'ref {self.ref!r} is not a string of A, C, G, T, N')
        if self.symbolic:
            self._check_symbolic()
        else:
            self._check_explicit()
        if self.chrom in _PAR and self._touches_par() and not self._in_par():
            raise ValueError(f'{self.chrom}:{self.pos}-{self.last} straddles a pseudoautosomal boundary')
        if self.chrom == 'chrY' and self._in_par():
            raise ValueError(f'chrY:{self.pos} is in a pseudoautosomal region, which the reference masks on chrY')
        return self

    def _check_symbolic(self) -> None:
        if len(self.ref) != 1:
            raise ValueError('a symbolic allele takes the single reference base at pos as ref')
        if self.end is None:
            raise ValueError(f'symbolic allele {self.alt} needs an end')
        if self.end < self.pos:
            raise ValueError(f'end {self.end} is before pos {self.pos}')
        if (self.alt == UPD) != (self.origin is not None):
            raise ValueError('an origin is given for <UPD>, and only for <UPD>')

    def _check_explicit(self) -> None:
        if not _BASES.fullmatch(self.alt):
            raise ValueError(f'alt {self.alt!r} is neither bases nor a symbolic allele')
        if self.alt == self.ref:
            raise ValueError('alt equals ref')
        if self.end is not None:
            raise ValueError('end is for symbolic alleles only')
        if self.origin is not None:
            raise ValueError('origin is for <UPD> only')


class Placement(visibility.WithheldModel, frozen=True):
    """One edit: put this variant on this haplotype. Every copy of a variant in every carrier is one row."""

    haplotype: Haplotype
    variant: Variant
    vaf: float | None = pydantic.Field(default=None, gt=0, lt=1)
    # The share of the member's reads at the site that carry the alternate allele because of this placement. On one of
    # two copies at most one half; a larger share on a diploid site is two placements. On a member's only copy any
    # share, as heteroplasmy needs. None: constitutional, every read of the copy.
