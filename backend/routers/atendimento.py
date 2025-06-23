from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os, requests
from datetime import datetime
from backend.database import SessionLocal
from backend import models
from backend.websocket_manager import conexoes_ativas

router = APIRouter(prefix="/atendimento", tags=["Atendimento"])

# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Configuração Evolution‑API
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://iasng-evolution-api.lu4llh.easypanel.host")
EVOLUTION_KEY = os.getenv("EVOLUTION_APIKEY") or os.getenv("EVOLUTION_KEY")
HEADERS       = {"apikey": EVOLUTION_KEY, "Content-Type": "application/json"} if EVOLUTION_KEY else {}

# ───────────────────────────────────────────────────────────────────────────────
# Schemas
# ───────────────────────────────────────────────────────────────────────────────
class MsgOut(BaseModel):
    cliente_id: int
    conteudo:   str

# ───────────────────────────────────────────────────────────────────────────────
# Rotas
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/clientes")
def listar_clientes(
    request: Request,
    empresa_id: int = Query(..., description="ID da empresa logada"),
    db: Session = Depends(get_db)
):
    """Lista clientes da empresa com último resumo de mensagem."""
    departamento = request.query_params.get("departamento")

    query = db.query(models.Cliente).filter(models.Cliente.empresa_id == empresa_id)
    if departamento:
        query = query.filter(models.Cliente.departamento == departamento)

    clientes  = query.all()
    resultado = []

    for c in clientes:
        ultima = (
            db.query(models.Mensagem)
              .filter_by(cliente_id=c.id)
              .order_by(models.Mensagem.timestamp.desc())
              .first()
        )

        possui_nao_lidas = (
            db.query(models.Mensagem)
              .filter_by(cliente_id=c.id, tipo="entrada", lida=False)
              .count() > 0
        )

        resultado.append({
            "id"      : c.id,
            "nome"    : c.nome,
            "telefone": c.telefone,
            "departamento": c.departamento,
            "avatar_url"  : c.avatar_url,  
            "ultima_mensagem": ultima.conteudo if ultima else "",
            "hora"          : ultima.timestamp.strftime("%H:%M") if ultima and ultima.timestamp else "",
            "novas"         : possui_nao_lidas,
        })
    return resultado


@router.get("/historico/{cliente_id}")
def historico_cliente(
    cliente_id: int,
    empresa_id: int = Query(..., description="ID da empresa logada"),
    db: Session = Depends(get_db)
):
    """Retorna o histórico do cliente **pertencente à empresa**."""
    cliente = db.query(models.Cliente).filter_by(id=cliente_id, empresa_id=empresa_id).first()
    if not cliente:
        raise HTTPException(404, "Cliente não encontrado para esta empresa.")

    mensagens = (
        db.query(models.Mensagem)
          .filter_by(cliente_id=cliente_id)
          .order_by(models.Mensagem.timestamp)
          .all()
    )

    # Marcar entradas como lidas
    for m in mensagens:
        if m.tipo == "entrada" and not m.lida:
            m.lida = True
    db.commit()

    return [
        {
            "conteudo": m.conteudo,
            "tipo":     m.tipo,
            "hora":     m.timestamp.strftime("%H:%M") if m.timestamp else "",
            "lida":     m.lida,
        }
        for m in mensagens
    ]


@router.post("/enviar")
async def enviar_mensagem(dados: MsgOut, db: Session = Depends(get_db)):
    """Atendente envia mensagem → grava, repassa à Evolution e faz broadcast."""
    cliente = db.query(models.Cliente).get(dados.cliente_id)
    if not cliente:
        raise HTTPException(404, "Cliente inexistente.")

    empresa = cliente.empresa

    # 1) Grava saída
    db.add(models.Mensagem(
        empresa_id = empresa.id,
        cliente_id = cliente.id,
        conteudo   = dados.conteudo,
        tipo       = "saida",
        lida       = True,
    ))
    db.commit()

    # 2) Evolution‑API
    if EVOLUTION_KEY:
        try:
            requests.post(
                f"{EVOLUTION_URL}/message/sendText/{empresa.instance_name}",
                json={"number": cliente.telefone, "text": dados.conteudo},
                headers=HEADERS,
                timeout=10,
            ).raise_for_status()
        except Exception as e:
            print("⚠️  Falha Evolution:", e)

    # 3) Broadcast WebSocket
    payload = {
        "empresa_id": empresa.id,
        "cliente_id": cliente.id,
        "telefone":   cliente.telefone,
        "mensagem":   dados.conteudo,
        "tipo":       "saida",
        "origem":     "atendente",
        "timestamp":  datetime.utcnow().isoformat()   # ➋ novo
    }

    for conn in list(conexoes_ativas):
        try:
            await conn.send_json(payload)
        except Exception:
            pass  # remove conexões quebradas depois, se quiser

    return {"status": "ok"}
