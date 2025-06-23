"""
Fluxo de onboarding:
1. Empresa informa nome + número → criamos instância na Evolution‑API.
2. Salva EMPRESA no banco (tabela empresas) com `instance_name` devolvido.
3. Configura webhook.
4. Devolve QR Code em base64 + id da empresa.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from slugify import slugify
import requests, os, re, uuid, typing as _t

from backend.database import SessionLocal
from backend import models

router = APIRouter(prefix="/empresas", tags=["Empresas"])

# ─────────────────────────────────────────────────────────────────────────────
# Helpers / dependências
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class EmpresaIn(BaseModel):
    empresa: str
    numero: str


def normalizar_numero(num: str) -> str:
    """Remove tudo que não for dígito (ex.: 31 98272‑8793 → 31982728793)."""
    return re.sub(r"\D", "", num)


def gerar_instance_name(empresa: str, numero: str) -> str:
    """Gera slug único: slug-da-empresa-4últimos‑4rand."""
    base   = slugify(empresa) or "empresa"
    sufixo = numero[-4:] if len(numero) >= 4 else numero
    rand   = uuid.uuid4().hex[:4]
    return f"{base}-{sufixo}-{rand}"


# ─────────────────────────────────────────────────────────────────────────────
# Configuração (env)
# ─────────────────────────────────────────────────────────────────────────────
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "https://iasng-evolution-api.lu4llh.easypanel.host")
EVOLUTION_KEY = os.getenv("EVOLUTION_APIKEY") or os.getenv("EVOLUTION_KEY")
WEBHOOK_URL   = os.getenv("WEBHOOK_URL")  # ex.: https://<ngrok>/webhook/evolution

if not EVOLUTION_KEY:
    raise RuntimeError("⚠️  Defina EVOLUTION_APIKEY/EVOLUTION_KEY no ambiente.")
if not WEBHOOK_URL:
    raise RuntimeError("⚠️  Defina WEBHOOK_URL no ambiente.")

HEADERS = {"apikey": EVOLUTION_KEY, "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# Rota principal
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/conectar")
def conectar_empresa(dados: EmpresaIn, db: Session = Depends(get_db)):
    """Cria (ou reconecta) uma empresa no sistema."""

    numero = normalizar_numero(dados.numero)
    if not numero:
        raise HTTPException(422, "Número inválido.")

    # 1) Evitar duplicidade ----------------------------------------------------
    if db.query(models.Empresa).filter_by(telefone=numero).first():
        raise HTTPException(400, "Número já cadastrado como empresa.")

    # 2) Criar instância na Evolution‑API -------------------------------------
    instance_name = gerar_instance_name(dados.empresa, numero)
    payload = {
        "instanceName": instance_name,
        "number":       numero,
        "integration":  "WHATSAPP-BAILEYS",
        "qrcode":       True,
    }

    r = requests.post(f"{EVOLUTION_URL}/instance/create",
                      json=payload, headers=HEADERS, timeout=15)

    if r.status_code == 403 and "already in use" in r.text.lower():
        raise HTTPException(409, "Nome de instância já em uso — tente novamente.")
    r.raise_for_status()

    data        = r.json()
    instance_id = data["instance"]["instanceId"]

    # 3) Registrar webhook (v2 → fallback v1) ----------------------------------
    events = ["QRCODE_UPDATED", "MESSAGES_UPSERT", "CONNECTION_UPDATE"]
    webhook_cfg = {
        "enabled":         True,
        "url":             WEBHOOK_URL,
        "webhookByEvents": True,
        "webhookBase64":   True,
        "events":          events,
    }

    w = requests.post(f"{EVOLUTION_URL}/instance/{instance_id}/webhook",
                      json={"webhook": webhook_cfg}, headers=HEADERS, timeout=10)

    if w.status_code == 404:
        # versão v2 não existe → tenta v1
        fallback = requests.post(f"{EVOLUTION_URL}/webhook/set/{instance_name}",
                                 json={"webhook": webhook_cfg},
                                 headers=HEADERS, timeout=10)
        fallback.raise_for_status()
    else:
        w.raise_for_status()

    # 4) Salva EMPRESA no banco -------------------------------------------------
    empresa = models.Empresa(
        nome          = dados.empresa,
        telefone      = numero,
        instance_name = instance_name
    )
    db.add(empresa); db.commit(); db.refresh(empresa)

    # 5) Extrair base64 do QR Code --------------------------------------------
    qrcode_field: _t.Any = data.get("qrcode")
    if isinstance(qrcode_field, dict):
        qrcode_b64 = qrcode_field.get("base64") or qrcode_field.get("image")
    else:
        qrcode_b64 = qrcode_field

    if not isinstance(qrcode_b64, str):
        raise HTTPException(502, "Evolution‑API não devolveu o QR Code em texto base64.")

    return {
        "empresa_id": empresa.id,
        "instance_id": instance_id,
        "instance_name": instance_name,
        "qrcode": {"base64": qrcode_b64},
        "mensagem": "Instância criada e webhook configurado!"
    }
