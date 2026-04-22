"""
Bootstrap: popula lookups canônicos (IBGE, partidos) e inicializa DuckDB.

Execução:
    python -m scripts.bootstrap

O que faz:
1. Baixa lista completa de municípios do IBGE API
2. Salva em lookups/municipios_br.csv
3. Cria lookups/partidos.csv com partidos brasileiros
4. Inicializa schema DuckDB em unified/warehouse.duckdb
5. Cria state/last_sync.json vazio
"""
import asyncio
import json
import logging
import pandas as pd
from pathlib import Path
from rich.logging import RichHandler
from rich.console import Console

logging.basicConfig(handlers=[RichHandler()], level=logging.INFO)
logger = logging.getLogger("sc_inteligencia.bootstrap")
console = Console()

BASE = Path(__file__).parent.parent

PARTIDOS = [
    {"numero": 10, "sigla_atual": "REPUBLICANOS", "espectro": "direita"},
    {"numero": 11, "sigla_atual": "PP", "espectro": "direita"},
    {"numero": 12, "sigla_atual": "PDT", "espectro": "centro-esquerda"},
    {"numero": 13, "sigla_atual": "PT", "espectro": "esquerda"},
    {"numero": 14, "sigla_atual": "PTB", "espectro": "centro-direita"},
    {"numero": 15, "sigla_atual": "MDB", "espectro": "centro"},
    {"numero": 17, "sigla_atual": "UNION", "espectro": "centro-direita"},
    {"numero": 20, "sigla_atual": "PODE", "espectro": "centro"},
    {"numero": 22, "sigla_atual": "PL", "espectro": "direita"},
    {"numero": 23, "sigla_atual": "CIDADANIA", "espectro": "centro"},
    {"numero": 25, "sigla_atual": "DEM", "espectro": "centro-direita"},
    {"numero": 30, "sigla_atual": "NOVO", "espectro": "direita"},
    {"numero": 33, "sigla_atual": "MOBILIZA", "espectro": "centro"},
    {"numero": 35, "sigla_atual": "PMN", "espectro": "centro"},
    {"numero": 36, "sigla_atual": "AGIR", "espectro": "centro"},
    {"numero": 40, "sigla_atual": "PSB", "espectro": "centro-esquerda"},
    {"numero": 43, "sigla_atual": "PV", "espectro": "centro-esquerda"},
    {"numero": 44, "sigla_atual": "UNIÃO", "espectro": "centro-direita"},
    {"numero": 45, "sigla_atual": "PSDB", "espectro": "centro"},
    {"numero": 50, "sigla_atual": "PSOL", "espectro": "esquerda"},
    {"numero": 51, "sigla_atual": "PATRIOTA", "espectro": "direita"},
    {"numero": 55, "sigla_atual": "PSD", "espectro": "centro"},
    {"numero": 65, "sigla_atual": "PC do B", "espectro": "esquerda"},
    {"numero": 70, "sigla_atual": "AVANTE", "espectro": "centro"},
    {"numero": 77, "sigla_atual": "SOLIDARIEDADE", "espectro": "centro"},
    {"numero": 80, "sigla_atual": "REDE", "espectro": "centro-esquerda"},
]

async def bootstrap():
    console.rule("[bold blue]Bootstrap sc-inteligencia")
    
    # 1. Criar diretórios
    for d in ["lookups", "raw", "normalized", "unified", "state", "public-json"]:
        (BASE / d).mkdir(parents=True, exist_ok=True)
    console.print("[green]✓[/] Diretórios criados")
    
    # 2. Baixar municípios IBGE
    console.print("Baixando municípios IBGE...")
    try:
        from src.collectors.ibge import IBGECollector
        collector = IBGECollector()
        municipios = await collector.listar_municipios_br()
        df_mun = pd.DataFrame(municipios)
        path_mun = BASE / "lookups" / "municipios_br.csv"
        df_mun.to_csv(path_mun, index=False)
        console.print(f"[green]✓[/] {len(df_mun)} municípios salvos em {path_mun}")
    except Exception as e:
        logger.error(f"Falha ao baixar municípios: {e}")
        raise
    
    # 3. Salvar partidos
    df_part = pd.DataFrame(PARTIDOS)
    path_part = BASE / "lookups" / "partidos.csv"
    df_part.to_csv(path_part, index=False)
    console.print(f"[green]✓[/] {len(df_part)} partidos salvos em {path_part}")
    
    # 4. Inicializar DuckDB
    try:
        import duckdb
        db_path = BASE / "unified" / "warehouse.duckdb"
        con = duckdb.connect(str(db_path))
        
        con.execute("""
            CREATE TABLE IF NOT EXISTS fato_emenda (
                ano INTEGER,
                numero_emenda VARCHAR,
                id_parlamentar_autor VARCHAR,
                tipo_rp VARCHAR,
                cod_ibge_destino BIGINT,
                uf_destino VARCHAR,
                funcao VARCHAR,
                subfuncao VARCHAR,
                objeto_resumido VARCHAR,
                favorecido_cnpj VARCHAR,
                valor_empenhado DECIMAL(18,2),
                valor_liquidado DECIMAL(18,2),
                valor_pago DECIMAL(18,2),
                valor_rp_inscrito DECIMAL(18,2),
                granularidade_perdida BOOLEAN,
                confianca_match FLOAT,
                rota_match VARCHAR,
                fontes VARCHAR,
                PRIMARY KEY (numero_emenda, cod_ibge_destino)
            )
        """)
        
        con.execute("""
            CREATE TABLE IF NOT EXISTS fato_voto (
                cod_ibge INTEGER,
                id_parlamentar VARCHAR,
                ano INTEGER,
                turno INTEGER,
                cargo VARCHAR,
                votos INTEGER,
                percentual_validos FLOAT,
                PRIMARY KEY (cod_ibge, id_parlamentar, ano, turno)
            )
        """)
        
        con.execute("""
            CREATE TABLE IF NOT EXISTS dim_municipio (
                cod_ibge INTEGER PRIMARY KEY,
                nome VARCHAR,
                nome_normalizado VARCHAR,
                uf VARCHAR(2),
                cod_uf INTEGER,
                regiao VARCHAR,
                mesorregiao VARCHAR,
                microrregiao VARCHAR,
                populacao_2022 INTEGER,
                eleitorado_2022 INTEGER,
                idhm FLOAT
            )
        """)
        
        con.execute("""
            CREATE TABLE IF NOT EXISTS dim_parlamentar (
                id VARCHAR PRIMARY KEY,
                casa VARCHAR,
                nome_completo VARCHAR,
                nome_urna VARCHAR,
                partido_atual VARCHAR,
                uf VARCHAR(2),
                legislatura INTEGER,
                id_camara INTEGER,
                id_tse_2022 INTEGER
            )
        """)
        
        # Inserir municípios no DW
        con.execute("DELETE FROM dim_municipio")
        con.register("df_mun_temp", df_mun)
        con.execute("""
            INSERT INTO dim_municipio 
            SELECT cod_ibge, nome, nome_normalizado, uf, cod_uf, regiao, 
                   mesorregiao, microrregiao, NULL, NULL, NULL
            FROM df_mun_temp
        """)
        
        con.close()
        console.print(f"[green]✓[/] DuckDB inicializado: {db_path}")
    except Exception as e:
        logger.error(f"Falha ao inicializar DuckDB: {e}")
        raise
    
    # 5. Inicializar state
    state_path = BASE / "state" / "last_sync.json"
    if not state_path.exists():
        state_path.write_text(json.dumps({}, indent=2))
        console.print(f"[green]✓[/] State inicializado: {state_path}")
    
    console.rule("[bold green]Bootstrap concluído!")
    console.print(
        f"\nPróximo passo:\n"
        f"  1. Copie .env.example para .env e preencha PORTAL_TRANSPARENCIA_API_KEY\n"
        f"  2. Execute: python -m scripts.run_mensal --fase 1 --uf SC"
    )

if __name__ == "__main__":
    asyncio.run(bootstrap())
