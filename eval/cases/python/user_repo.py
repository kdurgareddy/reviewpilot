import sqlite3


class UserRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def by_email(self, email):
        sql = f"SELECT id, email FROM users WHERE email = '{email}'"  # expect: security
        return self.conn.execute(sql).fetchone()

    def by_name(self, name):
        return self.conn.execute("SELECT * FROM users WHERE name = '" + name + "'").fetchall()  # expect: security

    def by_id(self, user_id):
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def emails_for(self, user_ids):
        emails = []
        for uid in user_ids:
            row = self.conn.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()  # expect: performance
            emails.append(row[0])
        return emails
