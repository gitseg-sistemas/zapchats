from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os, requests
from datetime import datetime

from backend.database import Base, engine, SessionLocal
from backend import models
from backend.websocket_manager import conexoes_ativas
from backend.routers import chatbot, atendimento, cliente_onboarding, mensagens

app = FastAPI()

# ───────────────────────────────────────────────────────────────
# Config Evolution‑API (avatar + envios) 
# ───────────────────────────────────────────────────────────────
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://iasng-evolution-api.lu4llh.easypanel.host")
EVOLUTION_KEY = os.getenv("EVOLUTION_APIKEY") or os.getenv("EVOLUTION_KEY")
HEADERS       = {"apikey": EVOLUTION_KEY} if EVOLUTION_KEY else {}

# ───────────────────────────────────────────────────────────────
# Rotas internas
# ───────────────────────────────────────────────────────────────
app.include_router(chatbot.router)
app.include_router(atendimento.router)
app.include_router(cliente_onboarding.router)
app.include_router(mensagens.router)

# ───────────────────────────────────────────────────────────────
# Frontend estático
# ───────────────────────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")

# ───────────────────────────────────────────────────────────────
# CORS
# ───────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────────────────────────────────────────────
# DB init
# ───────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ───────────────────────────────────────────────────────────────
# WebSocket
# ───────────────────────────────────────────────────────────────
@app.websocket("/ws/mensagens")
async def ws_msgs(ws: WebSocket):
    await ws.accept()
    conexoes_ativas.append(ws)
    print("✅ WS conectado")
    try:
        while True:
            await ws.receive_text()
    except Exception:
        print("❌ WS desconectado")
    finally:
        if ws in conexoes_ativas:
            conexoes_ativas.remove(ws)

auth_headers = {"Content-Type":"application/json"} | HEADERS

async def broadcast(data: dict):
    """Envia o payload para todas as conexões WebSocket ativas."""
    for c in list(conexoes_ativas):
        try:
            await c.send_json(data)
        except Exception:
            pass

# ───────────────────────────────────────────────────────────────
# Helper: avatar
# ───────────────────────────────────────────────────────────────
def fetch_avatar(instance_name: str, numero: str) -> str | None:
    """
    Busca a foto do contato via Evolution-API v2.
    """
    if not EVOLUTION_KEY:
        print("🚫 EVOLUTION_KEY ausente")
        return None

    url = f"{EVOLUTION_URL}/chat/fetchProfilePictureUrl/{instance_name}"
    try:
        r = requests.post(
            url,
            json={"number": numero},
            headers={"apikey": EVOLUTION_KEY, "Content-Type": "application/json"},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("profilePictureUrl")
        print("⚠️ avatar status:", r.status_code, r.text[:120])
    except Exception as e:
        print("⚠️ avatar erro:", e)
    return None
# ───────────────────────────────────────────────────────────────
# Webhook Evolution
# ───────────────────────────────────────────────────────────────
@app.post("/webhook/evolution")
async def webhook(request: Request):
    db = SessionLocal()
    try:
        p = await request.json()

        inst = p.get("instance")
        if not inst:
            return {"erro": "instance ausente"}

        empresa = db.query(models.Empresa).filter_by(instance_name=inst).first()
        if not empresa:
            return {"erro": "empresa não cadastrada"}

        key = p.get("data", {}).get("key", {})
        remote_jid = key.get("remoteJid")
        if not remote_jid:
            return {"erro": "remoteJid ausente"}
        numero = remote_jid.split("@")[0]

        # mensagem texto ---------------------------------------------------
        msg = (
            p.get("data", {}).get("message", {}).get("conversation")
            or p.get("body")
            or p.get("message")
            or ""
        )
        if not msg:
            return {"erro": "mensagem vazia"}

        # metadados ---------------------------------------------------------
        from_me = key.get("fromMe", False)
        tipo    = "saida"   if from_me else "entrada"
        origem  = "atendente" if from_me else "cliente"

        # cliente -----------------------------------------------------------
        cliente = (
            db.query(models.Cliente)
            .filter_by(empresa_id=empresa.id, telefone=numero)
            .first()
        )
        if not cliente and not from_me:
            # cria novo cliente para mensagens de entrada
            cliente = models.Cliente(
                empresa_id=empresa.id,
                telefone=numero,
                nome="Cliente",
            )
            db.add(cliente)
            db.commit()
            db.refresh(cliente)

        if not cliente:
            # Saída antes de existir cliente (bastante improvável). Apenas registra.
            return {"erro": "cliente inexistente; mensagem descartada"}

        # avatar -----------------------------------------------------------
        if not cliente.avatar_url and not from_me:
            avatar = fetch_avatar(inst, numero)
            if avatar:
                cliente.avatar_url = avatar
                db.commit()

        # grava mensagem ----------------------------------------------------
        db.add(
            models.Mensagem(
                empresa_id=empresa.id,
                cliente_id=cliente.id,
                conteudo=msg,
                tipo=tipo,
                lida=from_me,
            )
        )
        db.commit()

        # broadcast para UI -------------------------------------------------
        await broadcast(
            {
                "empresa_id": empresa.id,
                "cliente_id": cliente.id,
                "telefone": numero,
                "avatar_url": cliente.avatar_url,
                "mensagem": msg,
                "tipo": tipo,
                "origem": origem,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )
        return {"status": "ok"}

    except Exception as e:
        print("❌ webhook:", e)
        return {"erro": str(e)}

    finally:
        db.close()

# ───────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "API do ChatBot online"}
