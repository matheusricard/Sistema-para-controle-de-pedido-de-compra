import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "sistema_compras.db")

print("Banco de dados:", DB_FILE)

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

print("Apagando tabela 'usuarios' (se existir)...")
cur.execute("DROP TABLE IF EXISTS usuarios")

print("Criando tabela 'usuarios' com estrutura correta...")
cur.execute("""
    CREATE TABLE usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        senha TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0
    )
""")

print("Criando usuário 'admin' com senha 'admin' (admin = 1)...")
cur.execute(
    "INSERT INTO usuarios (username, senha, is_admin) VALUES (?, ?, ?)",
    ("admin", "admin", 1)
)

conn.commit()
conn.close()
print("Concluído. Usuário 'admin' criado com senha 'admin'.")
