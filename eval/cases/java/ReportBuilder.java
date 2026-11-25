package com.example.reports;

import java.util.List;

public class ReportBuilder {
    public String build(List<String> lines) {
        String out = "";
        for (String line : lines) {
            out += line + "\n"; // expect: performance
        }
        return out;
    }

    public String buildFast(List<String> lines) {
        StringBuilder sb = new StringBuilder();
        for (String line : lines) {
            sb.append(line).append('\n');
        }
        return sb.toString();
    }

    public int lastIndex(List<String> lines) {
        return lines.size(); // expect: bug
    }
}
