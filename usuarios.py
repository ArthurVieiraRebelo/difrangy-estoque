"""
usuarios.py
-----------
Cadastro de funcionários e verificação de senha.

Perfis:
    admin     -> faz tudo: cadastra/edita itens, ajustes de inventário,
                 usuários e backups.
    operador  -> bipa entradas e saídas e consulta as telas.

A SENHA NUNCA É GUARDADA. Guardamos só um "hash" dela: um texto embaralhado
que não dá para transformar de volta na senha. No login, a senha digitada
passa pelo mesmo embaralhamento e comparamos os resultados. Assim, mesmo
que alguém copie o arquivo do banco, não descobre as senhas.
As funções de hash vêm do Werkzeug, que já é instalado junto com o Flask.
"""

import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

import banco

PERFIS = {"admin": "Administrador", "operador": "Operador"}
TAMANHO_MINIMO_SENHA = 6


class ErroUsuario(Exception):
    """Erro de validação no cadastro de usuários (mensagem vai para a tela)."""


# ---------------------------------------------------------------- validações

def _validar_login(login):
    """Login: minúsculo, de 3 a 30 caracteres, só letras, números, ponto e _."""
    login = str(login or "").strip().lower()
    if not 3 <= len(login) <= 30:
        raise ErroUsuario("O login deve ter de 3 a 30 caracteres.")
    if not all(c.isascii() and (c.isalnum() or c in "._") for c in login):
        raise ErroUsuario("Use no login só letras sem acento, números, ponto ou _.")
    return login


def _validar_senha(senha):
    if len(senha or "") < TAMANHO_MINIMO_SENHA:
        raise ErroUsuario(f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
    return senha


def _validar_perfil(perfil):
    if perfil not in PERFIS:
        raise ErroUsuario("Perfil inválido.")
    return perfil


# ---------------------------------------------------------------- consultas

def contar_usuarios():
    return banco.consultar_um("SELECT COUNT(*) AS total FROM usuarios")["total"]


def buscar_por_id(id_usuario):
    return banco.consultar_um("SELECT * FROM usuarios WHERE id = ?", (id_usuario,))


def listar_usuarios():
    return banco.consultar("SELECT * FROM usuarios ORDER BY ativo DESC, nome")


def _contar_admins_ativos():
    return banco.consultar_um(
        "SELECT COUNT(*) AS total FROM usuarios WHERE perfil = 'admin' AND ativo = 1"
    )["total"]


def autenticar(login, senha):
    """Confere login e senha. Devolve o usuário se estiver certo, senão None."""
    usuario = banco.consultar_um(
        "SELECT * FROM usuarios WHERE login = ? AND ativo = 1",
        (str(login or "").strip().lower(),),
    )
    if usuario and check_password_hash(usuario["senha_hash"], senha or ""):
        return usuario
    return None


# ---------------------------------------------------------------- gravações

def criar_usuario(nome, login, senha, perfil):
    nome = str(nome or "").strip()
    if not nome:
        raise ErroUsuario("Preencha o nome.")
    login = _validar_login(login)
    _validar_senha(senha)
    _validar_perfil(perfil)
    try:
        banco.executar(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil) VALUES (?, ?, ?, ?)",
            (nome, login, generate_password_hash(senha), perfil),
        )
    except sqlite3.IntegrityError:
        raise ErroUsuario(f"Já existe um usuário com o login '{login}'.")
    return login


def alterar_senha(id_usuario, nova_senha):
    _validar_senha(nova_senha)
    banco.executar(
        "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
        (generate_password_hash(nova_senha), id_usuario),
    )


def trocar_propria_senha(usuario, senha_atual, nova_senha, confirmacao):
    """O próprio funcionário troca a senha (precisa saber a atual)."""
    if not check_password_hash(usuario["senha_hash"], senha_atual or ""):
        raise ErroUsuario("A senha atual está errada.")
    if nova_senha != confirmacao:
        raise ErroUsuario("A nova senha e a confirmação não são iguais.")
    alterar_senha(usuario["id"], nova_senha)


def alterar_usuario(id_alvo, perfil, ativo, quem_alterou):
    """Muda perfil e/ou ativa/desativa um usuário.

    Duas proteções para o sistema nunca ficar sem administrador:
    - ninguém desativa a si mesmo nem tira o próprio perfil de admin;
    - não dá para desativar/rebaixar o ÚLTIMO administrador ativo.
    """
    _validar_perfil(perfil)
    alvo = buscar_por_id(id_alvo)
    if alvo is None:
        raise ErroUsuario("Usuário não encontrado.")

    deixa_de_ser_admin_ativo = alvo["perfil"] == "admin" and alvo["ativo"] and (
        perfil != "admin" or not ativo
    )
    if deixa_de_ser_admin_ativo:
        if alvo["id"] == quem_alterou["id"]:
            raise ErroUsuario("Você não pode desativar nem tirar o seu próprio acesso de administrador.")
        if _contar_admins_ativos() <= 1:
            raise ErroUsuario("É preciso ter pelo menos um administrador ativo.")

    banco.executar(
        "UPDATE usuarios SET perfil = ?, ativo = ? WHERE id = ?",
        (perfil, 1 if ativo else 0, id_alvo),
    )
