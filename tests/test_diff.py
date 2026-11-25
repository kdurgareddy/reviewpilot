from conftest import SAMPLE

from reviewpilot.diff import detect_language, parse_diff, render_numbered

MODIFY = """diff --git a/app.py b/app.py
index 111..222 100644
--- a/app.py
+++ b/app.py
@@ -10,4 +10,5 @@ def handler():
     a = 1
-    b = 2
+    b = 3
+    c = 4
     return a
\\ No newline at end of file
"""


def test_added_lines_keep_new_file_numbers():
    [f] = parse_diff(MODIFY)
    assert f.path == "app.py" and f.status == "modified" and f.language == "python"
    assert f.added_lines == {11: "    b = 3", 12: "    c = 4"}
    assert [ln.kind for ln in f.hunks[0].lines] == [" ", "-", "+", "+", " "]
    assert f.hunks[0].lines[-1].number == 13


def test_sample_has_two_files_and_new_file_status():
    files = parse_diff(SAMPLE)
    assert [f.path for f in files] == ["app/orders.py", "web/src/Receipt.tsx"]
    assert files[1].status == "added" and files[1].language == "typescript"
    assert files[0].added_lines[8].startswith("PAYMENT_API_SECRET")


def test_deleted_files_are_dropped_and_renames_tracked():
    d = """diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
diff --git a/a.py b/b.py
similarity index 90%
rename from a.py
rename to b.py
--- a/a.py
+++ b/b.py
@@ -1,1 +1,2 @@
 keep = True
+added = True
"""
    files = parse_diff(d)
    assert [(f.path, f.status) for f in files] == [("b.py", "renamed")]
    assert files[0].added_lines == {2: "added = True"}


def test_multiple_hunks_and_lines_starting_with_markers():
    d = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,2 +1,2 @@
-old = 1
+--flag = 1
 same = 2
@@ -20,1 +20,2 @@
 z = 3
++plus = 4
"""
    [f] = parse_diff(d)
    assert f.added_lines == {1: "--flag = 1", 21: "+plus = 4"}


def test_render_numbered_and_language():
    [f, _] = parse_diff(SAMPLE)
    text = render_numbered(f)
    assert "    8 + PAYMENT_API_SECRET" in text
    assert detect_language("a/b/c.tsx") == "typescript" and detect_language("Makefile") == "text"


def test_test_file_detection():
    from reviewpilot.models import FileDiff
    for p in ["tests/test_a.py", "src/foo_test.py", "web/a.test.ts", "src/__tests__/x.js", "FooTest.java"]:
        assert FileDiff(p, p, "added").is_test, p
    assert not FileDiff("src/testing_utils.py", None, "added").is_test
