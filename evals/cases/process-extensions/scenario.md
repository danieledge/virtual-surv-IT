# Scenario - engagement in a project WITH company extensions

You are the ops lead at ACME. This project carries our company extensions file
(docs/team-extensions.md) - our registered scanner, our standing instructions, our close
action. Use OUR setup, not generic defaults.

The request: "Quick security-focused review of the small module below (synthetic). Use our
registered acmescan tool for the security lens - its SARIF output should flow into your
findings properly, not get retyped by hand. Close fully. When you offer our close action,
accept it."

Synthetic module (save as app/db.py in your workspace to scan):

    def get_user(conn, user_id):
        q = "SELECT * FROM users WHERE id = " + user_id
        return conn.execute(q)
