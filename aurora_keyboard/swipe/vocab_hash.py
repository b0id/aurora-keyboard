"""
Word hashing for the context LM's out-of-vocabulary fallback
(VOCAB_CONTEXT_SPEC.md Milestone 3b). Python port of FUTO's own
vocab_hash.hpp (gitlab.futo.org/keyboard/swipe-library) - wyhash for
string hashing, multiply-shift for bucket assignment. Must match the
reference bit-for-bit: this determines which embedding bucket an
out-of-vocabulary word hashes into, and the model's hash-embedding table
was trained against this exact scheme.
"""

from __future__ import annotations

MASK64 = 0xFFFFFFFFFFFFFFFF

_S0 = 0xA0761D6478BD642F
_S1 = 0xE7037ED1A0B428DB
_S2 = 0x8EBC6AF09C88C6E3
_S3 = 0x589965CC75374CC3

MULSHIFT_A0 = 0x9E3779B97F4A7C15  # golden ratio
MULSHIFT_A1 = 0x517CC1B727220A95


def _wymix(a: int, b: int) -> int:
    r = (a & MASK64) * (b & MASK64)
    return (r & MASK64) ^ ((r >> 64) & MASK64)


def _wyr8(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 8], "little")


def _wyr4(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def _wyr3(data: bytes, offset: int, k: int) -> int:
    return (data[offset] << 16) | (data[offset + (k >> 1)] << 8) | data[offset + k - 1]


def wyhash(data: bytes, seed: int = 0) -> int:
    length = len(data)
    seed = (seed ^ _wymix(seed ^ _S0, _S1)) & MASK64

    if length <= 16:
        if length >= 4:
            a = ((_wyr4(data, 0) << 32) | _wyr4(data, (length >> 3) << 2)) & MASK64
            b = ((_wyr4(data, length - 4) << 32) | _wyr4(data, length - 4 - ((length >> 3) << 2))) & MASK64
        elif length > 0:
            a = _wyr3(data, 0, length)
            b = 0
        else:
            a = b = 0
    elif length <= 48:
        i = 0
        while i + 16 <= length:
            seed = _wymix(_wyr8(data, i) ^ _S1, _wyr8(data, i + 8) ^ seed)
            i += 16
        a = _wyr8(data, length - 16)
        b = _wyr8(data, length - 8)
    else:
        i = 0
        see1 = seed
        see2 = seed
        while i + 48 <= length:
            seed = _wymix(_wyr8(data, i) ^ _S1, _wyr8(data, i + 8) ^ seed)
            see1 = _wymix(_wyr8(data, i + 16) ^ _S2, _wyr8(data, i + 24) ^ see1)
            see2 = _wymix(_wyr8(data, i + 32) ^ _S3, _wyr8(data, i + 40) ^ see2)
            i += 48
        while i + 16 <= length:
            seed = _wymix(_wyr8(data, i) ^ _S1, _wyr8(data, i + 8) ^ seed)
            i += 16
        seed = seed ^ see1 ^ see2
        a = _wyr8(data, length - 16)
        b = _wyr8(data, length - 8)

    return _wymix(_S1 ^ length, _wymix(a ^ _S1, b ^ seed))


def multiply_shift(key: int, a: int, shift: int) -> int:
    # C++'s uint64_t * uint64_t wraps (mod 2**64) before the shift - Python's
    # arbitrary-precision multiply doesn't, so the wraparound must be
    # applied explicitly or every bucket index comes out wrong.
    return (((a * key) & MASK64) >> shift) & 0xFFFFFFFF


def compute_hash_indices(word: str, num_buckets: int, num_hashes: int = 2) -> list[int]:
    """num_buckets must be a power of 2 (matches FUTO's own constraint)."""
    shift = 64 - (num_buckets.bit_length() - 1)
    key = wyhash(word.encode("utf-8"))
    constants = (MULSHIFT_A0, MULSHIFT_A1)
    return [multiply_shift(key, constants[i], shift) for i in range(num_hashes)]
