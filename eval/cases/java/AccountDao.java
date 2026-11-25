package com.example.bank;

import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;

public class AccountDao {
    private final Connection conn;

    public AccountDao(Connection conn) {
        this.conn = conn;
    }

    public ResultSet find(String owner) throws Exception {
        Statement st = conn.createStatement();
        return st.executeQuery("SELECT * FROM accounts WHERE owner = '" + owner + "'"); // expect: security
    }

    public ResultSet findSafe(String owner) throws Exception {
        PreparedStatement ps = conn.prepareStatement("SELECT * FROM accounts WHERE owner = ?");
        ps.setString(1, owner);
        return ps.executeQuery();
    }

    public String fingerprint(String pin) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5"); // expect: security
        return new String(md.digest(pin.getBytes()));
    }

    public void close() {
        try {
            conn.close();
        } catch (Exception e) {} // expect: bug
    }
}
