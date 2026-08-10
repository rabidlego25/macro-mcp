import io
import pathlib

import pytest
import sdmx

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def parse(payload: bytes):
    return sdmx.read_sdmx(io.BytesIO(payload))


@pytest.fixture
def load():
    return raw
