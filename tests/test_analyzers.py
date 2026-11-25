import asyncio

from conftest import SAMPLE, new_file_diff

from reviewpilot import review_diff
from reviewpilot.analyzers import ALL
from reviewpilot.diff import parse_diff


def rules_hit(code: str, path: str = "app/x.py", analyzer: str | None = None) -> set[str]:
    files = parse_diff(new_file_diff(path, code))
    names = [analyzer] if analyzer else list(ALL)
    return {f.rule_id for n in names for f in ALL[n]().run(files)}


def test_sample_findings_are_exact():
    r = asyncio.run(review_diff(SAMPLE))
    got = {(f.rule_id, f.line) for f in r.findings if f.file == "app/orders.py"}
    for expected in [("SEC003", 8), ("SEC004", 13), ("SEC004", 19), ("BUG004", 17), ("PERF001", 25),
                     ("PERF004", 26), ("PERF003", 27), ("SEC009", 32), ("BUG002", 33)]:
        assert expected in got, expected
    assert r.verdict == "request_changes"


def test_parameterised_sql_is_not_flagged():
    assert "SEC004" not in rules_hit('cur.execute("SELECT * FROM t WHERE id = %s", (uid,))')
    assert "SEC004" not in rules_hit('cur.execute("SELECT * FROM t WHERE id = ?", (uid,))')
    assert "SEC004" in rules_hit('cur.execute("SELECT * FROM t WHERE id = %s" % uid)')
    assert "SEC004" in rules_hit('cur.execute("SELECT * FROM t WHERE id = {}".format(uid))')


def test_secret_rules_skip_env_lookups_and_placeholders():
    assert "SEC003" in rules_hit('DB_PASSWORD = "hunter2-prod-pass"')
    assert "SEC003" not in rules_hit('DB_PASSWORD = os.environ["DB_PASSWORD"]')
    assert "SEC003" not in rules_hit('api_key = "your-api-key-here"')
    assert "SEC001" in rules_hit('KEY = "AKIAABCDEFGHIJKLMNOP"')
    # built at runtime so no key-shaped literal lives in the repo
    live = "sk_" + "live_" + "a1B2c3D4e5F6g7H8i9J0"
    assert "SEC015" in rules_hit(f'STRIPE = "{live}"')


def test_comments_are_ignored():
    assert rules_hit("# eval(user_input) would be bad here") == set()
    assert rules_hit("// el.innerHTML = x", "a.ts") == set()


def test_loop_and_async_context():
    loop = "def f(ids):\n    for i in ids:\n        db.execute('SELECT 1 FROM t WHERE id = ?', (i,))\n"
    assert "PERF001" in rules_hit(loop, analyzer="performance")
    no_loop = "def f(i):\n    db.execute('SELECT 1 FROM t WHERE id = ?', (i,))\n"
    assert "PERF001" not in rules_hit(no_loop, analyzer="performance")
    assert "PERF003" in rules_hit("async def f():\n    time.sleep(1)\n", analyzer="performance")
    assert "PERF003" not in rules_hit("def f():\n    time.sleep(1)\n", analyzer="performance")
    sibling = "def f(xs):\n    for x in xs:\n        print(x)\n    db.execute('SELECT 1')\n"
    assert "PERF001" not in rules_hit(sibling, analyzer="performance")


def test_bug_rules():
    assert "BUG004" in rules_hit("def f(a, b={}):\n    return b\n")
    assert "BUG005" in rules_hit("if x == None:\n    pass\n")
    assert "BUG006" in rules_hit("if level is 'gold':\n    pass\n")
    assert "BUG006" not in rules_hit("if level is None:\n    pass\n")
    assert "BUG003" in rules_hit("try { a(); } catch (e) {}", "a.ts")
    assert "BUG008" in rules_hit("if (a == b) {}", "a.ts")
    assert "BUG008" not in rules_hit("if (a === b || c == null) {}", "a.ts")


def test_testing_agent_flags_untested_code_but_not_when_tests_change():
    src = new_file_diff("app/billing.py", "def invoice_total(items):\n    return sum(items)\n")
    tst = new_file_diff("tests/test_billing.py", "from app.billing import invoice_total\n\n\ndef test_total():\n    assert invoice_total([1, 2]) == 3\n")
    only_src = asyncio.run(review_diff(src))
    assert [f.rule_id for f in only_src.findings] == ["TEST001"]
    both = asyncio.run(review_diff(src + tst))
    assert not [f for f in both.findings if f.rule_id == "TEST001"]


def test_test_without_assertions():
    tst = new_file_diff("tests/test_x.py", "def test_runs():\n    compute(1)\n\n\ndef test_ok():\n    assert compute(1) == 2\n")
    r = asyncio.run(review_diff(tst))
    assert [(f.rule_id, f.line) for f in r.findings] == [("TEST002", 1)]


def test_lockfiles_and_generated_files_are_ignored():
    d = new_file_diff("package-lock.json", '{"password": "supersecretvalue1"}') + new_file_diff("dist/app.min.js", "eval(x)")
    r = asyncio.run(review_diff(d))
    assert r.files_reviewed == 0 and r.findings == []
