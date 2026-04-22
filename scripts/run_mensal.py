"""
Orquestrador de ingestão mensal incremental.

Uso:
    python -m scripts.run_mensal --fase 1 --uf SC
    python -m scripts.run_mensal --fase 1 --uf BR  # todos os estados

Fases:
    1: Coleta IBGE + Câmara + Transparência + TransfereGov (críticos)
    2: FNS + FNDE + STN + MDS + SICONFI (complementares)
    3: Alesc + Transparência SC (estadual)
"""
import asyncio
import logging
import typer
from datetime import date
from pathlib import Path
from rich.logging import RichHandler
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

logging.basicConfig(handlers=[RichHandler()], level=logging.INFO)
logger = logging.getLogger("sc_inteligencia.run_mensal")
console = Console()
app = typer.Typer()

BASE = Path(__file__).parent.parent

@app.command()
def main(
    fase: int = typer.Option(1, help="Fase de coleta (1=críticos, 2=complementares, 3=estadual)"),
    uf: str = typer.Option("SC", help="UF alvo (SC ou BR para nacional)"),
    force: bool = typer.Option(False, help="Forçar re-ingestão mesmo se já sincronizado"),
    mes: str = typer.Option(None, help="Mês específico YYYY-MM (default: mês anterior)"),
):
    """Executa ingestão incremental mensal do sistema sc-inteligencia."""
    asyncio.run(_run(fase, uf, force, mes))

async def _run(fase: int, uf: str, force: bool, mes_override: str):
    from src.utils.state import SyncState
    from src.collectors.ibge import IBGECollector
    from src.collectors.camara import CamaraCollector
    from src.collectors.transparencia import TransparenciaCollector
    from src.collectors.transferegov import TransfereGovCollector
    from src.normalizers.municipio import MunicipioNormalizer
    from src.matchers.emenda_municipio import EmendaMunicipioMatcher
    from src.matchers.match_log import MatchLogger
    
    state = SyncState()
    
    if mes_override:
        meses = [mes_override]
    else:
        hoje = date.today()
        m = hoje.month - 1 if hoje.month > 1 else 12
        a = hoje.year if hoje.month > 1 else hoje.year - 1
        meses = [f"{a}-{m:02d}"]
    
    console.rule(f"[bold]Run Mensal — Fase {fase} — UF={uf} — Meses={meses}")
    
    # Carregar normalizer
    normalizer = MunicipioNormalizer()
    normalizer.carregar()
    match_logger = MatchLogger()
    matcher = EmendaMunicipioMatcher(normalizer, match_logger)
    
    if fase >= 1:
        await _fase1(uf, meses, normalizer, matcher, state, force)
    
    if fase >= 2:
        await _fase2(uf, meses, state, force)
    
    match_logger.flush()
    console.rule("[bold green]Concluído!")

async def _fase1(uf, meses, normalizer, matcher, state, force):
    """Fase 1: IBGE + Câmara + Transparência + TransfereGov."""
    from src.collectors.camara import CamaraCollector
    from src.collectors.transparencia import TransparenciaCollector
    import duckdb, pandas as pd
    from src.config import settings
    
    console.print("[bold cyan]Fase 1:[/] IBGE + Câmara + Transparência + TransfereGov")
    
    # 1a. Deputados da UF
    console.print("  → Deputados da Câmara...")
    camara = CamaraCollector()
    ufs = ["SC"] if uf == "SC" else _get_all_ufs()
    
    todos_deputados = []
    for u in ufs:
        deps = await camara.listar_deputados(uf=u)
        todos_deputados.extend(deps)
    console.print(f"  ✓ {len(todos_deputados)} deputados carregados")
    
    # 1b. Emendas por deputado
    transparencia = TransparenciaCollector()
    ano_atual = date.today().year
    
    total_emendas = 0
    total_resolvidas = 0
    total_uf_level = 0
    
    db = duckdb.connect(str(BASE / "unified" / "warehouse.duckdb"))
    
    for dep in todos_deputados:
        # Deputados federais de SC: usar ALIASES para o Portal da Transparência
        nome_portal = dep.get("nome_urna", dep.get("nome_completo", "")).upper()
        
        for ano in range(2023, ano_atual + 1):
            meses_pendentes = state.pending_months(f"transparencia_{dep['id_camara']}_{ano}")
            if not meses_pendentes and not force:
                continue
            
            emendas = await transparencia.buscar_emendas_autor(
                nome_portal, ano, uf_filtro=(uf if uf != "BR" else None)
            )
            
            for emenda in emendas:
                total_emendas += 1
                resolvidas = await matcher.resolver(emenda)
                
                for r in resolvidas:
                    if r.get("granularidade_perdida"):
                        total_uf_level += 1
                    else:
                        total_resolvidas += 1
                        # Inserir no DuckDB
                        try:
                            db.execute("""
                                INSERT OR REPLACE INTO fato_emenda
                                (ano, numero_emenda, id_parlamentar_autor, tipo_rp,
                                 cod_ibge_destino, uf_destino, funcao, subfuncao,
                                 objeto_resumido, valor_empenhado, valor_pago,
                                 granularidade_perdida, confianca_match, rota_match, fontes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, [
                                r.get("ano"), r.get("numero_emenda"),
                                dep["id"], r.get("tipo_rp"),
                                r.get("cod_ibge_destino"), r.get("uf_destino"),
                                r.get("funcao"), r.get("subfuncao"),
                                r.get("objeto_resumido"),
                                r.get("valor_empenhado", 0), r.get("valor_pago", 0),
                                r.get("granularidade_perdida", False),
                                r.get("confianca_match", 1.0),
                                r.get("rota_match", ""),
                                ",".join(r.get("fontes", [])),
                            ])
                        except Exception as e:
                            logger.warning(f"Erro ao inserir emenda {r.get('numero_emenda')}: {e}")
        
        state.set_synced(f"transparencia_{dep['id_camara']}_{ano_atual}", f"{date.today().year}-{date.today().month - 1:02d}")
    
    db.close()
    console.print(
        f"  ✓ {total_emendas} emendas processadas: "
        f"{total_resolvidas} municipalizadas, {total_uf_level} em nível UF"
    )

async def _fase2(uf, meses, state, force):
    """Fase 2: FNS + STN + MDS (placeholder para expansão)."""
    console.print("[bold cyan]Fase 2:[/] FNS + STN + MDS — stub implementado")
    # TODO: implementar coletores FNS, SICONFI, MDS com mesma estrutura incremental

def _get_all_ufs():
    return ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS",
            "MT","PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC",
            "SE","SP","TO"]

if __name__ == "__main__":
    app()
