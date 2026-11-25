# Benchmark cases

Each file is reviewed as if it were newly added in a pull request. A line a
reviewer should flag ends with a marker like `# expect: security` or
`// expect: bug, performance`. Markers are stripped before review. Files named
`clean_*` contain no issues and measure false positives.

Run: `reviewpilot eval` (uses your configured model) or `reviewpilot eval --offline`.
