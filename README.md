# Sistema de Compras (Flask) 🧾📊

**Compras sob controle, relatórios em um clique.**

Aplicação web em **Python (Flask)** para **gestão de pedidos de compras**, com **login**, **cadastro e listagem com filtros**, **dashboard gerencial** e **geração de relatórios em PDF** (ReportLab).  
Este repositório **não inclui banco de dados real** nem informações confidenciais.

> ⚠️ Aviso de confidencialidade: dados reais e arquivos sensíveis (ex.: `.db`, logos e informações internas) **foram removidos**. O banco SQLite é criado localmente ao rodar o projeto.

---

## ✅ Funcionalidades

- Autenticação com sessão (login/logout)
- Gestão de usuários (somente admin)
  - Listar usuários
  - Criar novo usuário
  - Alterar senha
- Pedidos
  - Cadastrar pedido (SC/PC/TAG/Status/Fornecedor/Valor/Obra etc.)
  - Listar pedidos
  - Filtros por **TAG(s)** e **Status**
- Dashboard
  - Totais (quantidade e valor)
  - Resumo por status
  - Últimos pedidos cadastrados
  - Top equipamentos por valor
  - Filtros por período, obra, veículo e tag
- Relatórios
  - Relatório geral em PDF (com totais e resumo por status)
  - Relatório por equipamento (TAG) em HTML e PDF

---

## 🧰 Tecnologias

- Python 3
- Flask
- SQLite (sqlite3)
- ReportLab (PDF)
- HTML (Jinja2 templates)

---

## 📦 Pré-requisitos

- Python 3.10+ (recomendado)
- pip


👤 Autor
Matheus (ADS)





