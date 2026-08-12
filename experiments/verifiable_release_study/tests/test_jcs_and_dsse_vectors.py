from __future__ import annotations

import json

import rfc8785

from amy_verifier.fixture_crypto import dsse_pae


def test_rfc8785_section_3_2_example() -> None:
    source = (
        '{"numbers":[333333333.33333329,1E30,4.50,2e-3,'
        '0.000000000000000000000000001],'
        '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\\"\\/",'
        '"literals":[null,true,false]}'
    )
    expected_hex = (
        "7b226c69746572616c73223a5b6e756c6c2c747275652c66616c73655d2c"
        "226e756d62657273223a5b3333333333333333332e333333333333332c3165"
        "2b33302c342e352c302e3030322c31652d32375d2c22737472696e67223a22"
        "e282ac245c75303030665c6e4127425c225c5c5c5c5c222f227d"
    )
    assert rfc8785.dumps(json.loads(source)) == bytes.fromhex(expected_hex)


def test_dsse_v1_preauthentication_encoding() -> None:
    assert dsse_pae(b"text/plain", b"hello") == b"DSSEv1 10 text/plain 5 hello"
