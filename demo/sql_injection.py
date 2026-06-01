import sqlite3


def get_user(conn: sqlite3.Connection, user_id: str):
    cur = conn.cursor()
    # VULN: user input concatenated straight into SQL -> SQL injection
    query = "SELECT * FROM users WHERE id = '" + user_id + "'"
    cur.execute(query)
    return cur.fetchall()


def safe_get_user(conn: sqlite3.Connection, user_id: str):
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))  # parameterized (OK)
    return cur.fetchall()
