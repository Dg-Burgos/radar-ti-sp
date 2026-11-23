import hashlib
import json
import os
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

FUSO_BR = timezone(timedelta(hours=-3))
AGORA = datetime.now(FUSO_BR)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )
}
ARQUIVO_DADOS = "dados.json"
DIAS_RETENCAO = 45

BANCAS_MAP = [
    ("VUNESP", [r"\bvunesp\b", r"funda[cç][aã]o vunesp"]),
    ("FGV", [r"\bfgv\b", r"get[uú]lio vargas"]),
    ("Cebraspe", [r"\bcebraspe\b", r"\bcespe\b"]),
    ("FCC", [r"\bfcc\b", r"carlos chagas"]),
    ("Instituto Mais", [r"instituto mais"]),
    ("Avança SP", [r"avan[cç]a\s*sp"]),
    ("INDEPAC", [r"\bindepac\b"]),
    ("IBFC", [r"\bibfc\b"]),
    ("IDECAN", [r"\bidecan\b"]),
    ("Instituto AOCP", [r"\baocp\b"]),
    ("Consulplan", [r"consulplan", r"instituto consulplan"]),
    ("Quadrix", [r"\bquadrix\b"]),
    ("FUVEST", [r"\bfuvest\b"]),
    ("SHDias", [r"\bshdias\b"]),
    ("RBO", [r"\brbo\b"]),
    ("NOSRUMO", [r"nosso\s*rumo"]),
]

TERMOS_TI_FORTES = [
    r"tecnologia da informa[cç][aã]o",
    r"analista de sistemas",
    r"analista de ti\b",
    r"analista em ti\b",
    r"especialista em ti\b",
    r"t[eé]cnico em inform[aá]tica",
    r"t[eé]cnico de inform[aá]tica",
    r"t[eé]cnico em ti\b",
    r"ci[eê]ncia de dados",
    r"cientista de dados",
    r"engenharia de software",
    r"engenheiro de software",
    r"seguran[cç]a da informa[cç][aã]o",
    r"infraestrutura de ti",
    r"desenvolvedor",
    r"programador",
    r"banco de dados",
    r"sistemas de informa[cç][aã]o",
    r"redes de computadores",
    r"gest[aã]o de ti",
    r"governan[cç]a de ti",
    r"auditor.*ti\b",
    r"perito.*inform[aá]tica",
    r"suporte t[eé]cnico",
    r"devops",
    r"arquitetura de software",
    r"\bt\.?i\.?\b",
]

TERMOS_SP = [
    r"s[aã]o paulo", r"\bsp\b", r"paulista", r"paulistano",
    r"\btjsp\b", r"tj-sp", r"\btrf[\s-]?3\b", r"\bsefaz[\s-]?sp\b",
    r"\bpcsp\b", r"pc-sp", r"\bmpsp\b", r"mp-sp", r"\btcesp\b", r"tce-sp",
    r"\balesp\b", r"\bprodesp\b", r"\bsabesp\b", r"\bcptm\b", r"\bifsp\b",
    r"\busp\b", r"\bunesp\b", r"\bunicamp\b", r"\bdpe[\s-]?sp\b",
    r"\bpge[\s-]?sp\b", r"\btrt[\s-]?2\b", r"\btrt[\s-]?15\b", r"\btre[\s-]?sp\b",
    r"campinas", r"guarulhos", r"santos", r"sorocaba", r"ribeir[aã]o preto",
    r"osasco", r"santo andr[eé]", r"s[aã]o bernardo", r"s[aã]o caetano",
    r"bauru", r"jundia[ií]", r"s[aã]o jos[eé] dos campos", r"piracicaba",
    r"mogi das cruzes", r"diadema", r"barueri", r"taubat[eé]", r"s[aã]o carlos",
    r"araraquara", r"mar[ií]lia", r"presidente prudente", r"ara[cç]atuba",
]

TERMOS_OUTROS_ESTADOS = [
    r"\brj\b", r"rio de janeiro", r"\bmg\b", r"minas gerais", r"\bba\b", r"bahia",
    r"\bpe\b", r"pernambuco", r"\bce\b", r"cear[aá]", r"\bpr\b", r"paran[aá]",
    r"\bsc\b", r"santa catarina", r"\brs\b", r"rio grande do sul", r"\bgo\b", r"goi[aá]s",
    r"\bam\b", r"amazonas", r"\bpa\b", r"par[aá]", r"\bma\b", r"maranh[aã]o",
    r"\bpi\b", r"piau[ií]", r"\bal\b", r"alagoas", r"\bse\b", r"sergipe",
    r"\bpb\b", r"para[ií]ba", r"\bes\b", r"esp[ií]rito santo", r"\bmt\b", r"mato grosso",
    r"\bdf\b", r"distrito federal", r"\bto\b", r"tocantins", r"\bro\b", r"rond[oô]nia",
]

ORDEM_ESTAGIO = {
    "Edital Aberto": 1,
    "Banca Definida": 2,
    "Comissão Formada": 3,
    "Autorizado": 4,
    "Previsto / Rumor": 5,
}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.lower()).strip()


def gerar_id(texto: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", normalizar(texto))[:90]
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def eh_ti(texto: str) -> bool:
    t = texto.lower()
    if re.search(r"no[cç][oõ]es de inform[aá]tica|curso de inform[aá]tica|pacote office", t):
        if not any(re.search(p, t) for p in TERMOS_TI_FORTES[:-1]):
            return False
    return any(re.search(p, t) for p in TERMOS_TI_FORTES)


def eh_sp_ou_federal(texto: str) -> bool:
    t = texto.lower()
    tem_sp = any(re.search(p, t) for p in TERMOS_SP)
    if tem_sp:
        return True
    eh_federal = bool(re.search(r"\bfederal\b|\bnacional\b|\bcnu\b|\bserpro\b|\bdataprev\b|\bbanco central\b|\breceita federal\b|\bpol[ií]cia federal\b|\bibge\b", t))
    tem_outro_estado = any(re.search(p, t) for p in TERMOS_OUTROS_ESTADOS)
    return eh_federal and not tem_outro_estado


def detectar_banca(texto: str) -> str:
    t = texto.lower()
    for nome, padroes in BANCAS_MAP:
        if any(re.search(p, t) for p in padroes):
            return nome
    return "Banca a Definir"


def detectar_estagio(texto: str, banca: str, fonte: str = "") -> str:
    t = texto.lower()
    if any(k in t for k in [
        "inscrições abertas", "inscricoes abertas", "edital publicado",
        "abre inscrições", "abre inscricoes", "edital aberto",
        "inscrições até", "inscricoes ate", "saiu o edital", "edital lançado"
    ]) or fonte == "PCI Concursos":
        return "Edital Aberto"

    if any(k in t for k in [
        "banca definida", "escolha da banca", "contrata banca", "banca contratada",
        "dispensa de licitação", "dispensa de licitacao", "extrato de contrato",
        "organizadora definida", "será organizado pela", "sera organizado pela"
    ]):
        return "Banca Definida"

    if any(k in t for k in [
        "comissão formada", "comissao formada", "comissão organizadora",
        "comissao organizadora", "grupo de trabalho", "projeto básico", "projeto basico"
    ]):
        return "Comissão Formada"

    if any(k in t for k in [
        "autorizado", "autoriza concurso", "autoriza a realização",
        "autorização publicada", "autorizacao publicada", "aval para concurso",
        "governador autoriza", "prefeito autoriza", "aprovado novo concurso"
    ]):
        return "Autorizado"

    if banca != "Banca a Definir" and any(k in t for k in ["edital iminente", "novo edital", "edital em breve"]):
        return "Banca Definida"

    return "Previsto / Rumor"


def detectar_esfera(texto: str) -> str:
    t = texto.lower()
    if re.search(r"\btrf\b|\btrt\b|\btre\b|\bifsp\b|\bfederal\b|\bnacional\b|\bcnu\b|\bserpro\b|\bdataprev\b|\binss\b|\bibge\b|\bbanco central\b|\breceita federal\b|\bpol[ií]cia federal\b|\bpf\b|\bprf\b|\banac\b|\banatel\b|\bcvm\b|\bbndes\b", t):
        return "Federal (SP)"
    if re.search(r"prefeitura|c[aâ]mara municipal|munic[ií]pio|municipal|guarda municipal|saae|prodam|sp trans|cet-sp", t):
        return "Municipal (SP)"
    return "Estadual (SP)"


def detectar_escolaridade(texto: str) -> str:
    t = texto.lower()
    tem_sup = bool(re.search(r"n[ií]vel superior|gradua[cç][aã]o|analista|especialista|auditor|perito|engenheiro|cientista|desenvolvedor", t))
    tem_med = bool(re.search(r"n[ií]vel m[eé]dio|n[ií]vel t[eé]cnico|t[eé]cnico em inform[aá]tica|t[eé]cnico de inform[aá]tica|t[eé]cnico em ti", t))
    if tem_sup and tem_med:
        return "Superior e Técnico/Médio"
    if tem_med:
        return "Técnico / Médio"
    if tem_sup:
        return "Superior"
    return "Não informado"


def limpar_titulo_google(titulo: str) -> tuple[str, str]:
    partes = titulo.rsplit(" - ", 1)
    if len(partes) == 2:
        return partes[0].strip(), partes[1].strip()
    return titulo.strip(), "Notícias"


def coletar_google_news() -> tuple[list[dict], dict]:
    consultas = [
        'concurso ("tecnologia da informação" OR "analista de sistemas" OR "técnico em informática" OR "TI") ("São Paulo" OR SP OR TJSP OR SEFAZ OR PCSP OR PRODESP) (autorizado OR comissão OR banca OR previsto OR edital)',
        'concurso Vunesp ("tecnologia da informação" OR "analista de sistemas" OR "informática" OR "TI" OR "sistemas")',
        'concurso ("tecnologia da informação" OR "analista de sistemas" OR "TI") ("TRF 3" OR "TRF3" OR "IFSP" OR "USP" OR "UNESP" OR "UNICAMP" OR "TRT 2" OR "TRT 15" OR "TRE SP")',
        'concurso prefeitura ("analista de sistemas" OR "tecnologia da informação" OR "técnico em informática") ("São Paulo" OR SP)',
    ]
    itens = []
    erros = 0

    for q in consultas:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:20]:
                titulo_bruto = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pub_date_str = item.findtext("pubDate") or ""
                titulo, veiculo = limpar_titulo_google(titulo_bruto)

                data_pub = AGORA.strftime("%Y-%m-%d")
                if pub_date_str:
                    try:
                        dt = parsedate_to_datetime(pub_date_str).astimezone(FUSO_BR)
                        if (AGORA - dt).days > 60:
                            continue
                        data_pub = dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                texto_analise = f"{titulo} {veiculo}"
                if not eh_ti(texto_analise) or not eh_sp_ou_federal(texto_analise):
                    continue

                banca = detectar_banca(texto_analise)
                itens.append({
                    "titulo": titulo,
                    "resumo": f"Capturado via {veiculo}.",
                    "url": link,
                    "fonte": f"Notícias ({veiculo})",
                    "banca": banca,
                    "estagio": detectar_estagio(texto_analise, banca),
                    "esfera": detectar_esfera(texto_analise),
                    "escolaridade": detectar_escolaridade(texto_analise),
                    "data_publicacao": data_pub,
                })
        except Exception:
            erros += 1

    status = {
        "nome": "Portais de Notícias (Rumores, Autorizações e Editais)",
        "ok": erros < len(consultas),
        "encontrados": len(itens),
    }
    return itens, status


def coletar_pci_concursos() -> tuple[list[dict], dict]:
    itens = []
    url = "https://www.pciconcursos.com.br/concursos/sudeste/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        blocos = soup.select("div.da, div.na, div.ca")

        for bloco in blocos:
            uf_el = bloco.select_one("div.cc")
            uf = uf_el.get_text(strip=True).upper() if uf_el else ""
            if uf and "SP" not in uf:
                continue

            link_el = bloco.select_one("a")
            if not link_el:
                continue

            orgao = link_el.get_text(" ", strip=True)
            href = link_el.get("href", "")
            detalhes_el = bloco.select_one("div.cd")
            detalhes = detalhes_el.get_text(" ", strip=True) if detalhes_el else ""
            prazo_el = bloco.select_one("div.ce")
            prazo = prazo_el.get_text(" ", strip=True) if prazo_el else ""

            texto_completo = f"{orgao} {detalhes} SP"
            if not eh_ti(texto_completo):
                continue

            banca = detectar_banca(texto_completo)
            resumo = detalhes[:240]
            if prazo:
                resumo = f"{resumo} | Prazo: {prazo}" if resumo else f"Prazo: {prazo}"

            itens.append({
                "titulo": f"{orgao} (SP)",
                "resumo": resumo or "Edital listado no PCI Concursos.",
                "url": href,
                "fonte": "PCI Concursos",
                "banca": banca,
                "estagio": detectar_estagio(texto_completo, banca, fonte="PCI Concursos"),
                "esfera": detectar_esfera(texto_completo),
                "escolaridade": detectar_escolaridade(texto_completo),
                "data_publicacao": AGORA.strftime("%Y-%m-%d"),
            })
        return itens, {"nome": "PCI Concursos (Editais Abertos SP)", "ok": True, "encontrados": len(itens)}
    except Exception:
        return [], {"nome": "PCI Concursos (Editais Abertos SP)", "ok": False, "encontrados": 0}


def coletar_querido_diario() -> tuple[list[dict], dict]:
    itens = []
    consultas = [
        '"autoriza" "concurso público" "informática"',
        '"comissão organizadora" "concurso público" "analista de sistemas"',
        '"banca organizadora" "concurso" "tecnologia da informação"',
    ]
    data_inicio = (AGORA - timedelta(days=30)).strftime("%Y-%m-%d")
    sucesso_alguma = False

    for q in consultas:
        try:
            resp = requests.get(
                "https://api.queridodiario.ok.org.br/api/gazettes",
                params={
                    "querystring": q,
                    "published_since": data_inicio,
                    "size": 15,
                    "sort_by": "descending_date",
                },
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            sucesso_alguma = True
            for g in resp.json().get("gazettes", []):
                if g.get("state_code") != "SP":
                    continue
                cidade = g.get("territory_name", "Município SP")
                trecho = " ".join(g.get("excerpts", []))[:280]
                trecho_limpo = re.sub(r"<[^>]+>", "", trecho).strip()
                texto_analise = f"Prefeitura de {cidade} SP {trecho_limpo}"
                if not eh_ti(texto_analise):
                    continue

                banca = detectar_banca(texto_analise)
                itens.append({
                    "titulo": f"Diário Oficial de {cidade} (SP) — Movimentação de Concurso TI",
                    "resumo": trecho_limpo or "Publicação oficial capturada no Diário Oficial municipal.",
                    "url": g.get("url") or "https://queridodiario.ok.org.br/",
                    "fonte": "Querido Diário (Diário Oficial)",
                    "banca": banca,
                    "estagio": detectar_estagio(texto_analise, banca),
                    "esfera": "Municipal (SP)",
                    "escolaridade": detectar_escolaridade(texto_analise),
                    "data_publicacao": g.get("date") or AGORA.strftime("%Y-%m-%d"),
                })
        except Exception:
            pass

    return itens, {
        "nome": "Querido Diário (Diários Oficiais Municipais SP)",
        "ok": sucesso_alguma,
        "encontrados": len(itens),
    }


def coletar_pncp() -> tuple[list[dict], dict]:
    itens = []
    consultas = [
        "banca organizadora concurso publico",
        "organizacao realizacao concurso publico vunesp",
    ]
    sucesso_alguma = False

    for q in consultas:
        try:
            resp = requests.get(
                "https://pncp.gov.br/api/search/",
                params={
                    "q": q,
                    "tipos_documento": "edital",
                    "ufs": "SP",
                    "ordenacao": "-data",
                    "pagina": 1,
                    "tam_pagina": 20,
                },
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            sucesso_alguma = True
            for doc in resp.json().get("items", []):
                orgao = doc.get("orgao_nome") or "Órgão Público SP"
                desc = doc.get("description") or doc.get("title") or ""
                municipio = doc.get("municipio_nome") or "SP"
                texto_analise = f"{orgao} {municipio} SP {desc}"

                if not re.search(r"concurso|banca|processo seletivo", texto_analise.lower()):
                    continue
                if not (eh_ti(texto_analise) or "vunesp" in texto_analise.lower()):
                    continue

                banca = detectar_banca(texto_analise)
                cnpj = re.sub(r"\D", "", str(doc.get("orgao_cnpj") or ""))
                ano = str(doc.get("ano") or "").strip()
                seq = str(doc.get("numero_sequencial") or "").strip().lstrip("0")

                if cnpj and ano and seq:
                    link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
                else:
                    item_url = (doc.get("item_url") or "").strip()
                    if item_url.startswith("/"):
                        caminho = item_url.replace("/compras/", "/editais/", 1)
                        link = f"https://pncp.gov.br{caminho}" if caminho.startswith("/app/") else f"https://pncp.gov.br/app{caminho}"
                    else:
                        link = f"https://pncp.gov.br/app/editais?q={urllib.parse.quote(orgao)}&status=todos&ufs=SP"

                data_pub = (doc.get("data_publicacao_pncp") or AGORA.strftime("%Y-%m-%d"))[:10]
                itens.append({
                    "titulo": f"{orgao} ({municipio}/SP) — Contratação de Banca",
                    "resumo": desc[:260],
                    "url": link,
                    "fonte": "PNCP (Contratações Públicas)",
                    "banca": banca,
                    "estagio": "Banca Definida" if banca != "Banca a Definir" else "Comissão Formada",
                    "esfera": detectar_esfera(texto_analise),
                    "escolaridade": detectar_escolaridade(texto_analise),
                    "data_publicacao": data_pub,
                })
        except Exception:
            pass

    return itens, {
        "nome": "PNCP (Contratação de Bancas em SP)",
        "ok": sucesso_alguma,
        "encontrados": len(itens),
    }


def carregar_historico() -> dict[str, dict]:
    if not os.path.exists(ARQUIVO_DADOS):
        return {}
    try:
        with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
            conteudo = json.load(f)
        return {item["id"]: item for item in conteudo.get("concursos", []) if "id" in item}
    except Exception:
        return {}


def main():
    historico = carregar_historico()
    coletados = []
    status_fontes = []

    for func in [coletar_google_news, coletar_pci_concursos, coletar_querido_diario, coletar_pncp]:
        itens, st = func()
        coletados.extend(itens)
        status_fontes.append(st)

    mapa_final = {}

    # Mantém itens recentes do histórico para não perder registros entre coletas
    limite_data = (AGORA - timedelta(days=DIAS_RETENCAO)).strftime("%Y-%m-%d")
    for item_id, antigo in historico.items():
        if antigo.get("ultima_vez_visto", "2000-01-01") >= limite_data:
            if "pncp.gov.br/app/compras/" in antigo.get("url", ""):
                antigo["url"] = antigo["url"].replace("pncp.gov.br/app/compras/", "pncp.gov.br/app/editais/")
            mapa_final[item_id] = antigo

    hoje_str = AGORA.strftime("%Y-%m-%d")
    for item in coletados:
        item_id = gerar_id(item["titulo"])
        anterior = mapa_final.get(item_id)

        primeira_vez = anterior["primeira_vez_visto"] if anterior else hoje_str
        mudou_fase = False
        estagio_anterior = anterior.get("estagio") if anterior else None

        if anterior and estagio_anterior and estagio_anterior != item["estagio"]:
            if ORDEM_ESTAGIO.get(item["estagio"], 9) < ORDEM_ESTAGIO.get(estagio_anterior, 9):
                mudou_fase = True
            else:
                item["estagio"] = estagio_anterior

        item["id"] = item_id
        item["primeira_vez_visto"] = primeira_vez
        item["ultima_vez_visto"] = hoje_str
        item["mudou_fase"] = mudou_fase or (anterior.get("mudou_fase", False) if anterior else False)
        mapa_final[item_id] = item

    # Marca selo NOVO para itens vistos pela primeira vez nos últimos 7 dias
    lista_final = []
    for item in mapa_final.values():
        try:
            dt_visto = datetime.strptime(item["primeira_vez_visto"], "%Y-%m-%d").replace(tzinfo=FUSO_BR)
            item["novo"] = (AGORA - dt_visto).days <= 7
        except Exception:
            item["novo"] = False
        lista_final.append(item)

    # Ordena: VUNESP no topo -> Estágio mais avançado -> Mais recente
    lista_final.sort(
        key=lambda x: (
            0 if x["banca"] == "VUNESP" else 1,
            ORDEM_ESTAGIO.get(x["estagio"], 9),
            x.get("data_publicacao", ""),
        )
    )
    # Reordena data decrescente preservando prioridade VUNESP e estágio
    lista_final.sort(key=lambda x: x.get("data_publicacao", ""), reverse=True)
    lista_final.sort(key=lambda x: ORDEM_ESTAGIO.get(x["estagio"], 9))
    lista_final.sort(key=lambda x: 0 if x["banca"] == "VUNESP" else 1)

    saida = {
        "ultima_atualizacao": AGORA.strftime("%d/%m/%Y às %H:%M (Horário de Brasília)"),
        "total": len(lista_final),
        "fontes": status_fontes,
        "concursos": lista_final,
    }

    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(f"Radar TI-SP atualizado com {len(lista_final)} registros.")


if __name__ == "__main__":
    main()
