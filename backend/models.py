from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Empresa(Base):
    __tablename__ = "empresas"
    id            = Column(Integer, primary_key=True, index=True)
    nome          = Column(String)
    telefone      = Column(String)
    instance_name = Column(String, unique=True)
    clientes = relationship(
        "Cliente",
        back_populates="empresa",
        cascade="all, delete-orphan"
    )

class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (
        UniqueConstraint("empresa_id", "telefone", name="u_empresa_cliente"),
    )

    id         = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"))
    nome       = Column(String, default="Cliente")
    telefone   = Column(String)
    departamento = Column(String, nullable=True)

    # 👇 novo campo
    avatar_url = Column(String, nullable=True)

    # relacionamentos
    empresa   = relationship("Empresa", back_populates="clientes")
    mensagens = relationship("Mensagem", back_populates="cliente")
class Mensagem(Base):
    __tablename__ = "mensagens"

    id         = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"))
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    conteudo   = Column(Text)
    tipo       = Column(String)                         # “entrada” | “saida”
    lida       = Column(Boolean, default=False)
    timestamp  = Column(DateTime, default=datetime.utcnow)

    # ─ relacionamentos
    cliente = relationship("Cliente", back_populates="mensagens")
