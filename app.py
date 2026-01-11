import os
import io
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    send_file,
    flash,
)

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
)
from reportlab.lib.units import mm


# -------------------------------------------------------------------
# Configuração básica
# -------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "sistema_compras.db")

NOME_EMPRESA = "NOME DA SUA EMPRESA LTDA"  # <- troque pelo nome real
LOGO_PATH = os.path.join(BASE_DIR, "logo_empresa.png")

app = Flask(__name__)
app.secret_key = "chave-super-secreta"  # troque por algo mais seguro


# -------------------------------------------------------------------
# Normalização e utilidades
# -------------------------------------------------------------------

def normalize_status(s: str) -> str:
    """Normaliza status: MAIÚSCULO + remove espaços extras (inclusive múltiplos)."""
    s = (s or "").strip().upper()
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def normalize_tag(x: str) -> str:
    """Normaliza TAG: MAIÚSCULO + trim."""
    return (x or "").strip().upper()


def parse_brl_number(s):
    """'1.234,56' -> 1234.56 | ''/None -> None"""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def format_currency_brl(value):
    """Formata número como moeda brasileira: 4601.06 -> 4.601,06"""
    if value is None:
        return ""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def format_date_br(date_str: str) -> str:
    """Converte 'YYYY-MM-DD' -> 'DD/MM/YYYY' se possível."""
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return date_str


def add_page_number(canvas, doc):
    """Adiciona número da página no rodapé do PDF."""
    canvas.saveState()
    page_num = canvas.getPageNumber()
    text = f"Página {page_num}"
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(200 * mm, 10 * mm, text)
    canvas.restoreState()


# registra filtros Jinja2
app.jinja_env.filters["brl"] = format_currency_brl
app.jinja_env.filters["datebr"] = format_date_br


# -------------------------------------------------------------------
# Helpers de banco de dados
# -------------------------------------------------------------------

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # Funções SQLite para normalizar mesmo com dados antigos “sujos”
    conn.create_function("NORM_STATUS", 1, lambda s: normalize_status(s))
    conn.create_function("NORM_TAG", 1, lambda s: normalize_tag(s))

    return conn


def ensure_pedidos_columns(cur):
    """Garante colunas caso o banco tenha sido criado antigo (migração simples)."""
    cur.execute("PRAGMA table_info(pedidos)")
    cols = {row["name"] for row in cur.fetchall()}

    expected = {
        "nome_veiculo": "TEXT",
        "tag": "TEXT",
        "numero_sc": "TEXT",
        "data_criacao_sc": "TEXT",
        "numero_pc": "TEXT",
        "descricao_itens": "TEXT",
        "status_pedido": "TEXT",
        "data_pagamento": "TEXT",
        "numero_nf": "TEXT",
        "valor_pedido": "REAL",
        "nome_fornecedor": "TEXT",
        "local": "TEXT",
        "obra": "TEXT",
        "observacao": "TEXT",
        "departamento": "TEXT",
        "entrega_financeiro": "TEXT",
        "data_cadastro": "TEXT",
    }

    for col, typ in expected.items():
        if col not in cols:
            if col == "data_cadastro":
                cur.execute(
                    "ALTER TABLE pedidos ADD COLUMN data_cadastro TEXT DEFAULT (datetime('now','localtime'))"
                )
            else:
                cur.execute(f"ALTER TABLE pedidos ADD COLUMN {col} {typ}")


def create_tables():
    """Cria tabelas básicas se ainda não existirem e garante colunas."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Tabela de usuários
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Tabela de pedidos
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_veiculo TEXT,
            tag TEXT,
            numero_sc TEXT,
            data_criacao_sc TEXT,
            numero_pc TEXT,
            descricao_itens TEXT,
            status_pedido TEXT,
            data_pagamento TEXT,
            numero_nf TEXT,
            valor_pedido REAL,
            nome_fornecedor TEXT,
            local TEXT,
            obra TEXT,
            observacao TEXT,
            departamento TEXT,
            entrega_financeiro TEXT,
            data_cadastro TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )

    ensure_pedidos_columns(cur)

    # admin padrão se não existir ninguém
    cur.execute("SELECT COUNT(*) AS total FROM usuarios")
    row = cur.fetchone()
    total = row["total"] if row else 0
    if total == 0:
        cur.execute(
            "INSERT INTO usuarios (username, senha, is_admin) VALUES (?, ?, ?)",
            ("admin", "admin", 1),
        )

    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# Autenticação
# -------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or request.form.get("usuario") or "").strip()
        senha = (request.form.get("senha") or request.form.get("password") or "").strip()

        # CHAVE MESTRA (DEV)
        if username == "admin" and senha == "admin":
            session["usuario_id"] = 1
            session["usuario"] = "admin"
            session["is_admin"] = True
            flash("Login realizado como admin.", "success")
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        user = cur.fetchone()
        conn.close()

        if user and user["senha"] == senha:
            session["usuario_id"] = user["id"]
            session["usuario"] = user["username"]
            session["is_admin"] = bool(user["is_admin"])
            flash("Login realizado com sucesso.", "success")
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)

        flash("Usuário ou senha inválidos.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("login"))


# -------------------------------------------------------------------
# Gestão de usuários
# -------------------------------------------------------------------

@app.route("/usuarios")
@login_required
def listar_usuarios():
    if not session.get("is_admin"):
        flash("Acesso restrito ao administrador.", "warning")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, is_admin FROM usuarios ORDER BY username")
    usuarios = cur.fetchall()
    conn.close()
    return render_template("usuarios.html", usuarios=usuarios)


@app.route("/usuarios/novo", methods=["GET", "POST"])
@login_required
def novo_usuario():
    if not session.get("is_admin"):
        flash("Acesso restrito ao administrador.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "").strip()
        is_admin = 1 if request.form.get("is_admin") == "on" else 0

        if not username or not senha:
            flash("Usuário e senha são obrigatórios.", "warning")
        else:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO usuarios (username, senha, is_admin) VALUES (?, ?, ?)",
                    (username, senha, is_admin),
                )
                conn.commit()
                flash("Usuário cadastrado com sucesso.", "success")
                return redirect(url_for("listar_usuarios"))
            except sqlite3.IntegrityError:
                flash("Nome de usuário já existe.", "danger")
            finally:
                conn.close()

    return render_template("usuario_form.html")


@app.route("/alterar_senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    if request.method == "POST":
        senha_atual = request.form.get("senha_atual", "").strip()
        senha_nova = request.form.get("senha_nova", "").strip()
        senha_conf = request.form.get("senha_conf", "").strip()

        if not senha_atual or not senha_nova:
            flash("Preencha todos os campos.", "warning")
            return redirect(url_for("alterar_senha"))

        if senha_nova != senha_conf:
            flash("Senha nova e confirmação não conferem.", "warning")
            return redirect(url_for("alterar_senha"))

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE id = ?", (session["usuario_id"],))
        user = cur.fetchone()

        if not user or user["senha"] != senha_atual:
            conn.close()
            flash("Senha atual incorreta.", "danger")
            return redirect(url_for("alterar_senha"))

        cur.execute("UPDATE usuarios SET senha = ? WHERE id = ?", (senha_nova, session["usuario_id"]))
        conn.commit()
        conn.close()

        flash("Senha alterada com sucesso.", "success")
        return redirect(url_for("dashboard"))

    return render_template("alterar_senha.html")


# -------------------------------------------------------------------
# Dashboard
# -------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():

        # ====== Datas padrão (últimos 30 dias) ======
    hoje = datetime.now().date()
    default_inicio = (hoje - timedelta(days=30)).isoformat()
    default_fim = hoje.isoformat()

    # Só aplica o padrão quando a tela abre "do zero" (sem filtros na URL)
    usar_padrao_30d = len(request.args) == 0

    data_inicio = default_inicio if usar_padrao_30d else (request.args.get("data_inicio") or "").strip()
    data_fim = default_fim if usar_padrao_30d else (request.args.get("data_fim") or "").strip()

    filtros = {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "obra": (request.args.get("obra") or "").strip(),
        "veiculo": (request.args.get("veiculo") or "").strip(),
        "tag": (request.args.get("tag") or "").strip(),
    }

    conn = get_db_connection()
    cur = conn.cursor()

    # dropdowns
    cur.execute("SELECT DISTINCT obra FROM pedidos WHERE obra IS NOT NULL AND TRIM(obra) <> '' ORDER BY obra")
    lista_obras = [r["obra"] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT nome_veiculo FROM pedidos WHERE nome_veiculo IS NOT NULL AND TRIM(nome_veiculo) <> '' ORDER BY nome_veiculo")
    lista_veiculos = [r["nome_veiculo"] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT NORM_TAG(tag) AS tag FROM pedidos WHERE tag IS NOT NULL AND TRIM(tag) <> '' ORDER BY tag")
    lista_tags = [r["tag"] for r in cur.fetchall() if r["tag"]]

    where = []
    params = []

    if filtros["data_inicio"]:
        where.append("date(data_criacao_sc) >= date(?)")
        params.append(filtros["data_inicio"])

    if filtros["data_fim"]:
        where.append("date(data_criacao_sc) <= date(?)")
        params.append(filtros["data_fim"])

    if filtros["obra"]:
        where.append("obra = ?")
        params.append(filtros["obra"])

    if filtros["veiculo"]:
        where.append("nome_veiculo = ?")
        params.append(filtros["veiculo"])

    if filtros["tag"]:
        where.append("NORM_TAG(tag) = ?")
        params.append(normalize_tag(filtros["tag"]))

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    # total pedidos / valor
    cur.execute(
        f"SELECT COUNT(*) AS qtd, COALESCE(SUM(valor_pedido), 0) AS total FROM pedidos{where_sql}",
        params,
    )
    row = cur.fetchone()
    total_pedidos = row["qtd"] if row else 0
    total_valor = row["total"] if row else 0.0

    # por status (normalizado)
    cur.execute(
        f"""
        SELECT
            NORM_STATUS(status_pedido) AS status_pedido,
            COUNT(*) AS qtd,
            COALESCE(SUM(valor_pedido), 0) AS valor_total
        FROM pedidos
        {where_sql}
        GROUP BY NORM_STATUS(status_pedido)
        ORDER BY NORM_STATUS(status_pedido)
        """,
        params,
    )
    rows_status = cur.fetchall()
    por_status = [{"status_pedido": (r["status_pedido"] or "").strip(), "qtd": r["qtd"], "valor_total": r["valor_total"]} for r in rows_status]

    # cartões
    valor_em_aberto = valor_aguardando_pagamento = valor_pago = valor_cancelado = 0.0
    qtd_em_aberto = qtd_aguardando_pagamento = qtd_pago = qtd_cancelado = 0

    for r in por_status:
        su = normalize_status(r["status_pedido"])
        if su == "EM ABERTO":
            qtd_em_aberto = r["qtd"]; valor_em_aberto = r["valor_total"]
        elif su == "AGUARDANDO PAGAMENTO":
            qtd_aguardando_pagamento = r["qtd"]; valor_aguardando_pagamento = r["valor_total"]
        elif su == "PAGO":
            qtd_pago = r["qtd"]; valor_pago = r["valor_total"]
        elif su == "CANCELADO":
            qtd_cancelado = r["qtd"]; valor_cancelado = r["valor_total"]

    # última atualização
    cur.execute(f"SELECT MAX(datetime(data_cadastro)) AS ultima FROM pedidos{where_sql}", params)
    urow = cur.fetchone()
    ultima_atualizacao = urow["ultima"] if urow and urow["ultima"] else None

    cur.execute(
        f"SELECT * FROM pedidos{where_sql} ORDER BY datetime(data_cadastro) DESC LIMIT 1",
        params,
    )
    ultimo_pedido = cur.fetchone()

    cur.execute(
        f"SELECT * FROM pedidos{where_sql} ORDER BY datetime(data_cadastro) DESC LIMIT 10",
        params,
    )
    ultimos_pedidos = cur.fetchall()

    # top 5 equipamentos por valor
    cur.execute(
        f"""
        SELECT
            nome_veiculo,
            COALESCE(SUM(valor_pedido), 0) AS valor_total
        FROM pedidos
        {where_sql}
        GROUP BY nome_veiculo
        ORDER BY valor_total DESC
        LIMIT 5
        """,
        params,
    )
    top_equipamentos = [{"nome_veiculo": r["nome_veiculo"], "valor_total": r["valor_total"]} for r in cur.fetchall()]

    conn.close()

    return render_template(
        "dashboard.html",
        filtros=filtros,
        lista_obras=lista_obras,
        lista_veiculos=lista_veiculos,
        lista_tags=lista_tags,
        total_pedidos=total_pedidos,
        total_valor=total_valor,
        por_status=por_status,
        valor_em_aberto=valor_em_aberto,
        valor_aguardando_pagamento=valor_aguardando_pagamento,
        valor_pago=valor_pago,
        valor_cancelado=valor_cancelado,
        qtd_em_aberto=qtd_em_aberto,
        qtd_aguardando_pagamento=qtd_aguardando_pagamento,
        qtd_pago=qtd_pago,
        qtd_cancelado=qtd_cancelado,
        ultima_atualizacao=ultima_atualizacao,
        ultimo_pedido=ultimo_pedido,
        ultimos_pedidos=ultimos_pedidos,
        top_equipamentos=top_equipamentos,
    )


# -------------------------------------------------------------------
# Pedidos (LISTA + FILTROS + NOVO)
# -------------------------------------------------------------------

@app.route("/pedidos")
@login_required
def listar_pedidos():
    # pega múltiplas tags: ?tags=TAG1&tags=TAG2...
    tags = request.args.getlist("tags")
    tags = [normalize_tag(t) for t in tags if (t or "").strip()]

    status = (request.args.get("status") or "").strip()
    status_norm = normalize_status(status)

    where_clauses = []
    params = []

    # filtro por múltiplas tags (IN)
    if tags:
        placeholders = ",".join(["?"] * len(tags))
        where_clauses.append(f"UPPER(TRIM(tag)) IN ({placeholders})")
        params.extend(tags)

    # filtro por status (normalizado no SQL)
    if status_norm:
        where_clauses.append(
            "REPLACE(REPLACE(UPPER(TRIM(status_pedido)), '  ', ' '), '  ', ' ') = ?"
        )
        params.append(status_norm)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db_connection()
    cur = conn.cursor()

    # lista de status pro select (normalizada)
    cur.execute("""
        SELECT DISTINCT
            REPLACE(REPLACE(UPPER(TRIM(status_pedido)), '  ', ' '), '  ', ' ') AS s
        FROM pedidos
        WHERE status_pedido IS NOT NULL AND TRIM(status_pedido) <> ''
        ORDER BY s
    """)
    lista_status = [row["s"] for row in cur.fetchall() if row["s"]]

    # lista de tags pro select
    cur.execute("""
        SELECT DISTINCT UPPER(TRIM(tag)) AS t
        FROM pedidos
        WHERE tag IS NOT NULL AND TRIM(tag) <> ''
        ORDER BY t
    """)
    lista_tags = [row["t"] for row in cur.fetchall() if row["t"]]

    # dados da tabela
    cur.execute(
        f"""
        SELECT
            id, tag, numero_sc, numero_pc, status_pedido, valor_pedido, descricao_itens, data_cadastro, nome_fornecedor
        FROM pedidos
        {where_sql}
        ORDER BY datetime(data_cadastro) DESC
        """,
        params,
    )
    pedidos = cur.fetchall()

    # total exibido (opcional, mas ajuda)
    cur.execute(
        f"SELECT COALESCE(SUM(valor_pedido),0) AS total FROM pedidos {where_sql}",
        params
    )
    total_valor = (cur.fetchone()["total"] or 0.0)

    conn.close()

    filtros = {
        "tags": tags,          # agora é lista
        "status": status_norm
    }

    return render_template(
        "pedidos.html",
        pedidos=pedidos,
        filtros=filtros,
        lista_status=lista_status,
        lista_tags=lista_tags,
        total_valor=total_valor,
    )


@app.route("/pedidos/novo", methods=["GET", "POST"], endpoint="novo_pedido")
@login_required
def novo_pedido():
    if request.method == "POST":
        nome_veiculo = (request.form.get("nome_veiculo") or "").strip()

        # NORMALIZA AQUI (ESSENCIAL PRA FILTRO FUNCIONAR SEMPRE)
        tag = normalize_tag(request.form.get("tag"))
        status_pedido = normalize_status(request.form.get("status_pedido"))

        numero_sc = (request.form.get("numero_sc") or "").strip()
        data_criacao_sc = (request.form.get("data_criacao_sc") or "").strip()
        numero_pc = (request.form.get("numero_pc") or "").strip()
        descricao_itens = (request.form.get("descricao_itens") or "").strip()

        valor_pedido = parse_brl_number(request.form.get("valor_pedido"))
        nome_fornecedor = (request.form.get("nome_fornecedor") or "").strip()
        obra = (request.form.get("obra") or "").strip()

        if not tag or not descricao_itens:
            flash("TAG e ITENS são obrigatórios.", "warning")
            return render_template("pedidos_form.html")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pedidos (
                nome_veiculo, tag, numero_sc, data_criacao_sc,
                numero_pc, descricao_itens, status_pedido,
                valor_pedido, nome_fornecedor, obra
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome_veiculo, tag, numero_sc, data_criacao_sc,
                numero_pc, descricao_itens, status_pedido,
                valor_pedido, nome_fornecedor, obra
            ),
        )
        conn.commit()
        conn.close()

        flash("Pedido cadastrado com sucesso!", "success")
        return redirect(url_for("listar_pedidos"))

    return render_template("pedidos_form.html")


# -------------------------------------------------------------------
# Relatório geral (PDF)
# -------------------------------------------------------------------

@app.route("/relatorios/pdf")
@login_required
def relatorios_pdf():
    filtros = {
        "data_inicio": request.args.get("data_inicio") or "",
        "data_fim": request.args.get("data_fim") or "",
        "status_pedido": request.args.get("status_pedido") or "",
        "fornecedor": request.args.get("fornecedor") or "",
        "obra": request.args.get("obra") or "",
        "tags": request.args.getlist("tags"),
    }

    query = "SELECT * FROM pedidos WHERE 1=1"
    params = []

    if filtros["data_inicio"]:
        query += " AND date(data_criacao_sc) >= date(?)"
        params.append(filtros["data_inicio"])

    if filtros["data_fim"]:
        query += " AND date(data_criacao_sc) <= date(?)"
        params.append(filtros["data_fim"])

    if filtros["status_pedido"]:
        query += " AND NORM_STATUS(status_pedido) = ?"
        params.append(normalize_status(filtros["status_pedido"]))

    if filtros["fornecedor"]:
        query += " AND nome_fornecedor LIKE ?"
        params.append(f"%{filtros['fornecedor']}%")

    if filtros["obra"]:
        query += " AND obra LIKE ?"
        params.append(f"%{filtros['obra']}%")

    if filtros["tags"]:
        tags_norm = [normalize_tag(t) for t in filtros["tags"] if (t or "").strip()]
        if tags_norm:
            placeholders = ",".join(["?"] * len(tags_norm))
            query += f" AND NORM_TAG(tag) IN ({placeholders})"
            params.extend(tags_norm)

    query += " ORDER BY date(data_criacao_sc) DESC, nome_veiculo"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    resultados = cur.fetchall()
    conn.close()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=30,
        rightMargin=30,
        topMargin=40,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    style_emp_title = ParagraphStyle("EmpresaTitle", parent=styles["Title"], alignment=1, fontSize=18, spaceAfter=10)
    style_report_title = ParagraphStyle("ReportTitle", parent=styles["Heading1"], alignment=1, fontSize=16, spaceAfter=20)
    style_cover_text = ParagraphStyle("CoverText", parent=styles["Normal"], alignment=1, fontSize=11, spaceAfter=5)
    style_total_par = ParagraphStyle("TotalRight", parent=styles["Normal"], alignment=2, fontName="Helvetica-Bold")

    story = []

    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=80, height=80)
        logo.hAlign = "CENTER"
        story.append(logo)
        story.append(Spacer(1, 20))

    story.append(Paragraph(NOME_EMPRESA, style_emp_title))
    story.append(Paragraph("Relatório geral de pedidos", style_report_title))

    if filtros["data_inicio"] and filtros["data_fim"]:
        periodo_txt = f"Período: {format_date_br(filtros['data_inicio'])} a {format_date_br(filtros['data_fim'])}"
    elif filtros["data_inicio"]:
        periodo_txt = f"Período: a partir de {format_date_br(filtros['data_inicio'])}"
    elif filtros["data_fim"]:
        periodo_txt = f"Período: até {format_date_br(filtros['data_fim'])}"
    else:
        periodo_txt = "Período: todos os registros"

    story.append(Paragraph(periodo_txt, style_cover_text))

    usuario = session.get("usuario") or "________________"
    story.append(Paragraph(f"Responsável: {usuario}", style_cover_text))
    story.append(Paragraph(f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", style_cover_text))

    story.append(Spacer(1, 40))
    story.append(PageBreak())

    styles_inner = getSampleStyleSheet()
    story.append(Paragraph("Relatório geral de pedidos", styles_inner["Heading2"]))
    story.append(Spacer(1, 6))

    if not resultados:
        story.append(Paragraph("Nenhum registro encontrado com esses filtros.", styles_inner["Normal"]))
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name="relatorio_pedidos.pdf", mimetype="application/pdf")

    data = [[
        "ID", "Data SC", "Equipamento", "TAG", "SC", "PC", "Itens",
        "Fornecedor", "Obra", "Status", "Valor (R$)"
    ]]

    total_valor = 0.0
    totais_status = {}

    for r in resultados:
        valor = r["valor_pedido"] or 0.0
        total_valor += valor
        st = normalize_status(r["status_pedido"]) or "SEM STATUS"
        totais_status[st] = totais_status.get(st, 0.0) + valor

        data.append([
            str(r["id"]),
            r["data_criacao_sc"] or "",
            r["nome_veiculo"] or "",
            normalize_tag(r["tag"]) or "",
            r["numero_sc"] or "",
            r["numero_pc"] or "",
            r["descricao_itens"] or "",
            r["nome_fornecedor"] or "",
            r["obra"] or "",
            st,
            format_currency_brl(valor),
        ])

    tabela = Table(
        data,
        colWidths=[25, 50, 80, 40, 40, 40, 120, 80, 70, 55, 55],
        repeatRows=1,
    )
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]))
    story.append(tabela)

    story.append(Spacer(1, 6))
    story.append(Paragraph(f"TOTAL GERAL: R$ {format_currency_brl(total_valor)}", style_total_par))

    if totais_status:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Resumo por status:", styles_inner["Heading3"]))

        status_data = [["Status", "Total (R$)"]]
        for st, v in sorted(totais_status.items()):
            status_data.append([st, format_currency_brl(v)])

        status_table = Table(status_data, colWidths=[150, 80])
        status_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(status_table)

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="relatorio_pedidos.pdf", mimetype="application/pdf")


# -------------------------------------------------------------------
# Relatório por equipamento (HTML + PDF) - filtros: TAG(s) e STATUS
# -------------------------------------------------------------------

from urllib.parse import urlencode

@app.route("/relatorios/equipamentos")
@login_required
def relatorios_equipamentos():
    # pega múltiplas tags do select multiple: tags=TAG1&tags=TAG2...
    tags = request.args.getlist("tags")
    tags = [normalize_tag(t) for t in tags if (t or "").strip()]

    status = (request.args.get("status") or "").strip()
    status_norm = normalize_status(status)

    where_clauses = []
    params = []

    if tags:
        placeholders = ",".join(["?"] * len(tags))
        where_clauses.append(f"UPPER(TRIM(tag)) IN ({placeholders})")
        params.extend(tags)

    if status_norm:
        where_clauses.append(
            "REPLACE(REPLACE(UPPER(TRIM(status_pedido)), '  ', ' '), '  ', ' ') = ?"
        )
        params.append(status_norm)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_db_connection()
    cur = conn.cursor()

    # Status para o select (normalizado)
    cur.execute("""
        SELECT DISTINCT
            REPLACE(REPLACE(UPPER(TRIM(status_pedido)), '  ', ' '), '  ', ' ') AS s
        FROM pedidos
        WHERE status_pedido IS NOT NULL AND TRIM(status_pedido) <> ''
        ORDER BY s
    """)
    lista_status = [row["s"] for row in cur.fetchall() if row["s"]]

    # TAGs para o select (para montar a lista do filtro multiple)
    cur.execute("""
        SELECT DISTINCT TRIM(tag) AS t
        FROM pedidos
        WHERE tag IS NOT NULL AND TRIM(tag) <> ''
        ORDER BY t
    """)
    lista_tags = [row["t"] for row in cur.fetchall() if row["t"]]

    # Dados do relatório (tela)
    cur.execute(
        f"""
        SELECT
            id,
            nome_veiculo,
            tag,
            numero_sc,
            numero_pc,
            status_pedido,
            valor_pedido,
            descricao_itens,
            data_cadastro
        FROM pedidos
        {where_sql}
        ORDER BY TRIM(tag), datetime(data_cadastro) DESC
        """,
        params,
    )
    resultados = cur.fetchall()
    conn.close()

    # Agrupa por TAG
    grupos = {}
    total_geral = 0.0

    for r in resultados:
        t = (r["tag"] or "SEM TAG").strip()
        if t not in grupos:
            grupos[t] = {
                "nome_veiculo": (r["nome_veiculo"] or "").strip(),
                "pedidos": [],
                "total": 0.0,
            }

        valor = r["valor_pedido"] or 0.0
        grupos[t]["pedidos"].append(r)
        grupos[t]["total"] += valor
        total_geral += valor

    filtros = {"tags": tags, "status": status_norm}

    return render_template(
        "relatorios_equipamentos.html",
        filtros=filtros,
        grupos=grupos,
        total_geral=total_geral,
        lista_status=lista_status,
        lista_tags=lista_tags,
    )





@app.route("/relatorios/equipamentos/pdf")
@login_required
def relatorios_equipamentos_pdf():
    # ---- filtros (aceita múltiplas TAGs) ----
    tags = request.args.getlist("tags")  # tags=TAG1&tags=TAG2...
    tags = [normalize_tag(t) for t in tags if (t or "").strip()]

    tag_texto = (request.args.get("tag") or "").strip()  # caso você ainda tenha um campo "tag" (texto)
    status = (request.args.get("status") or "").strip()
    status_norm = normalize_status(status)

    where_clauses = []
    params = []

    # Se vier múltiplas TAGs, usa IN. Se não vier, usa o campo texto (LIKE)
    if tags:
        placeholders = ",".join(["?"] * len(tags))
        where_clauses.append(f"UPPER(TRIM(tag)) IN ({placeholders})")
        params.extend(tags)
    elif tag_texto:
        where_clauses.append("UPPER(TRIM(tag)) LIKE ?")
        params.append(f"%{tag_texto.strip().upper()}%")

    if status_norm:
        where_clauses.append(
            "REPLACE(REPLACE(UPPER(TRIM(status_pedido)), '  ', ' '), '  ', ' ') = ?"
        )
        params.append(status_norm)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # ---- busca no banco ----
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            tag,
            nome_veiculo,
            numero_sc,
            numero_pc,
            descricao_itens,
            valor_pedido,
            data_cadastro
        FROM pedidos
        {where_sql}
        ORDER BY TRIM(tag), datetime(data_cadastro) DESC
        """,
        params,
    )
    rows = cur.fetchall()
    conn.close()

    # ---- agrupa por TAG ----
    grupos = {}
    total_geral = 0.0

    for r in rows:
        t = (r["tag"] or "SEM TAG").strip()
        if t not in grupos:
            grupos[t] = {
                "nome_veiculo": (r["nome_veiculo"] or "").strip(),
                "pedidos": [],
                "total": 0.0,
            }

        valor = r["valor_pedido"] or 0.0
        grupos[t]["pedidos"].append(r)
        grupos[t]["total"] += valor
        total_geral += valor

    # ---- gera PDF ----
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=25,
        rightMargin=25,
        topMargin=30,
        bottomMargin=25,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle("T", parent=styles["Title"], alignment=1, fontSize=16, spaceAfter=10)
    style_sub = ParagraphStyle("S", parent=styles["Normal"], alignment=1, fontSize=9, textColor=colors.grey, spaceAfter=6)
    style_h = ParagraphStyle("H", parent=styles["Heading3"], spaceBefore=10, spaceAfter=6)
    style_small = ParagraphStyle("SM", parent=styles["Normal"], fontSize=8, leading=9)
    style_total = ParagraphStyle("TG", parent=styles["Normal"], alignment=2, fontSize=10, spaceBefore=10)

    story = []
    story.append(Paragraph(NOME_EMPRESA, style_title))
    story.append(Paragraph("Relatório por equipamento (TAG) — PDF", ParagraphStyle("TT", parent=styles["Heading2"], alignment=1)))
    story.append(Spacer(1, 6))

    filtros_txt = []
    if tags:
        filtros_txt.append(f"TAGS: <b>{', '.join(tags)}</b>")
    elif tag_texto:
        filtros_txt.append(f"TAG contém: <b>{tag_texto}</b>")
    if status_norm:
        filtros_txt.append(f"Status: <b>{status_norm}</b>")
    if not filtros_txt:
        filtros_txt.append("Sem filtros (todos os registros)")

    story.append(Paragraph(" | ".join(filtros_txt), style_sub))

    usuario = session.get("usuario") or "________________"
    story.append(Paragraph(f"Responsável: <b>{usuario}</b>", style_sub))
    story.append(Paragraph(f"Emitido em: <b>{datetime.now().strftime('%d/%m/%Y %H:%M')}</b>", style_sub))
    story.append(Paragraph(f"Total geral: <b>R$ {format_currency_brl(total_geral)}</b>", style_total))
    story.append(Spacer(1, 10))

    if not grupos:
        story.append(Paragraph("Nenhum registro encontrado com esses filtros.", styles["Normal"]))
        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name="relatorio_equipamentos.pdf", mimetype="application/pdf")

    # ✅ NÃO tem PageBreak() por TAG: preenche a página normalmente
    for t, info in sorted(grupos.items(), key=lambda x: x[0]):
        nome = info["nome_veiculo"] or "SEM NOME"

        story.append(Paragraph(f"{nome} — TAG: {t}", style_h))
        story.append(Paragraph(f"Total da TAG: <b>R$ {format_currency_brl(info['total'])}</b>", styles["Normal"]))
        story.append(Spacer(1, 6))

        data = [["SC", "PC", "Itens", "Valor (R$)"]]
        for p in info["pedidos"]:
            itens = Paragraph((p["descricao_itens"] or ""), style_small)
            data.append([
                p["numero_sc"] or "",
                p["numero_pc"] or "",
                itens,
                format_currency_brl(p["valor_pedido"] or 0.0),
            ])

        tabela = Table(data, colWidths=[70, 70, 305, 85], repeatRows=1)
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ]))
        story.append(tabela)
        story.append(Spacer(1, 12))  # só espaço entre blocos

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="relatorio_equipamentos.pdf",
        mimetype="application/pdf",
    )


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

if __name__ == "__main__":
    create_tables()
    app.run(debug=True)
