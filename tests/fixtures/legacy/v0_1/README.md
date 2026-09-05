# Preserved v0.1 serialized artifacts

These files are deliberately **not** kept current. They are byte-level evidence of what
a v0.1 artifact looked like, so `tests/test_contract_compat_v02.py` can prove that the
0.2 migration path actually loads a real 0.1 file rather than a hand-written
approximation of one.

Do not "fix up" the `schema_version` or the `SCREAMING_SNAKE` `WorkClass` tokens here.
Correcting them would delete the only thing these fixtures exist to test.

The canonical, current-contract fixtures live in `tests/fixtures/valid/`.
