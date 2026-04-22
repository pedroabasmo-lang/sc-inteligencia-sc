"""
Matcher emenda↔município — Cascata de resolução conforme Seção 6 do prompt.

Algoritmo:
1. Se emenda já tem cod_ibge_destino → match exato, confiança 1.0
2. Se destino é 'UF' ou 'Múltiplo':
   a. Consultar TransfereGov por numero_emenda
   b. Se função=10-Saúde: consultar FNS
   c. Se função=12-Educação: registrar como FNDE (stub)
   d. Consultar DOU por portaria (stub)
   e. Se nada resolve: granularidade_perdida=True, match_log nao_resolvido

NUNCA distribui valor agregado entre municípios sem base factual.
Valores não resolvidos ficam em card UF-level com flag granularidade_perdida.
"""
import logging
from decimal import Decimal
from typing import Optional
from src.collectors.transferegov import TransfereGovCollector
from src.collectors.fns import FNSCollector
from src.matchers.match_log import MatchLogger
from src.normalizers.municipio import MunicipioNormalizer

logger = logging.getLogger("sc_inteligencia.matchers.emenda_municipio")

class EmendaMunicipioMatcher:
    """
    Resolve emendas com destino 'UF' ou 'Múltiplo' para municípios específicos.
    
    Implementa a cascata obrigatória da Seção 6 do sistema.
    """
    
    def __init__(
        self,
        normalizer: MunicipioNormalizer,
        match_logger: Optional[MatchLogger] = None,
    ):
        self.normalizer = normalizer
        self.log = match_logger or MatchLogger()
        self.transferegov = TransfereGovCollector()
        self.fns = FNSCollector()
    
    async def resolver(self, emenda: dict) -> list[dict]:
        """
        Resolve uma emenda para lista de registros municipalizados.
        
        Args:
            emenda: dict normalizado do TransparenciaCollector
        
        Returns:
            Lista de dicts com cod_ibge preenchido, ou lista com 1 item
            com granularidade_perdida=True se não resolveu.
        """
        numero = emenda.get("numero_emenda", "")
        cod_ibge = emenda.get("cod_ibge_destino")
        funcao = str(emenda.get("funcao") or "")
        
        # PASSO 1: já tem município — retorna direto
        if cod_ibge and cod_ibge > 1000000:
            mun = self.normalizer.por_ibge(cod_ibge)
            self.log.registrar(
                numero_emenda=numero,
                cod_ibge=cod_ibge,
                origem_fonte="portal_transparencia",
                chave_usada="codigoMunicipioIBGE",
                tipo_match="exato",
                confianca=1.0,
            )
            return [self._enriquecer(emenda, cod_ibge, 1.0, "exato", "portal_transparencia")]
        
        logger.info(f"Emenda {numero}: destino UF/Múltiplo — iniciando cascata")
        resultados = []
        
        # PASSO 2: TransfereGov
        try:
            te_results = await self.transferegov.buscar_por_numero_emenda(numero)
            if te_results:
                for r in te_results:
                    ibge = r.get("cod_ibge")
                    if ibge:
                        self.log.registrar(
                            numero_emenda=numero,
                            cod_ibge=ibge,
                            origem_fonte="portal_transparencia",
                            chave_usada=f"numero_emenda→transferegov ({r.get('tipo_instrumento')})",
                            tipo_match="exato",
                            confianca=1.0,
                            destino_fonte="transferegov",
                            destino_registro=r.get("nr_instrumento", ""),
                        )
                        resultados.append(self._enriquecer(
                            emenda, ibge,
                            confianca=1.0,
                            tipo_match="exato",
                            fonte=r.get("fonte", "transferegov"),
                            valor_override=r.get("valor_pago"),
                        ))
                if resultados:
                    logger.info(f"Emenda {numero}: resolvida via TransfereGov ({len(resultados)} municípios)")
                    return resultados
        except Exception as e:
            logger.warning(f"TransfereGov falhou para {numero}: {e}")
        
        # PASSO 3: FNS para emendas de saúde
        if "10" in funcao or "saúde" in funcao.lower():
            try:
                # FNS requer portaria — tentar extrair do objeto
                portaria = emenda.get("portaria_dou")
                if portaria:
                    fns_results = await self.fns.buscar_por_portaria(portaria)
                    if fns_results:
                        for r in fns_results:
                            ibge_raw = r.get("cod_ibge") or r.get("codIBGE")
                            if ibge_raw:
                                try:
                                    ibge = int(str(ibge_raw))
                                    self.log.registrar(
                                        numero_emenda=numero,
                                        cod_ibge=ibge,
                                        origem_fonte="portal_transparencia",
                                        chave_usada=f"portaria_dou→fns",
                                        tipo_match="inferido",
                                        confianca=0.85,
                                        destino_fonte="fns",
                                    )
                                    resultados.append(self._enriquecer(
                                        emenda, ibge, 0.85, "inferido", "fns"
                                    ))
                                except (ValueError, TypeError):
                                    pass
                        if resultados:
                            logger.info(f"Emenda {numero}: resolvida via FNS ({len(resultados)} municípios)")
                            return resultados
            except Exception as e:
                logger.warning(f"FNS falhou para {numero}: {e}")
        
        # PASSO 4/5: FNDE e DOU — stubs (endpoints a confirmar empiricamente)
        if "12" in funcao or "educação" in funcao.lower():
            logger.info(f"Emenda {numero}: função educação — FNDE stub (implementar endpoint)")
        
        # PASSO 6: Não resolvido — marcar como granularidade_perdida
        valor_total = Decimal(str(emenda.get("valor_empenhado") or 0))
        logger.warning(
            f"Emenda {numero}: granularidade perdida — "
            f"R${valor_total:,.2f} em nível UF sem resolução municipal"
        )
        self.log.registrar_nao_resolvido(
            numero_emenda=numero,
            origem_fonte="portal_transparencia",
            motivo="TransfereGov e FNS não retornaram municípios — valor mantido em nível UF",
        )
        
        return [{
            **emenda,
            "cod_ibge_destino": None,
            "granularidade_perdida": True,
            "rota_match": "nao_resolvido",
            "confianca_match": 0.0,
        }]
    
    def _enriquecer(
        self,
        emenda: dict,
        cod_ibge: int,
        confianca: float,
        tipo_match: str,
        fonte: str,
        valor_override: Optional[float] = None,
    ) -> dict:
        """Retorna cópia da emenda com município resolvido e metadados de match."""
        result = {**emenda}
        result["cod_ibge_destino"] = cod_ibge
        result["granularidade_perdida"] = False
        result["confianca_match"] = confianca
        result["tipo_match"] = tipo_match
        result["rota_match"] = fonte
        if valor_override is not None:
            result["valor_pago"] = valor_override
        if fonte not in result.get("fontes", []):
            result.setdefault("fontes", []).append(fonte)
        return result
