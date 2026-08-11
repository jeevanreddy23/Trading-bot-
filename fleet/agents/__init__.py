from .commodities import CommoditiesAgent
from .crypto_arb import CryptoArbAgent
from .crypto_momentum import CryptoMomentumAgent
from .fx import FXAgent
from .stocks import StocksAgent

REGISTRY = {
    "crypto_arb": (CryptoArbAgent, "crypto"),
    "crypto_momentum": (CryptoMomentumAgent, "crypto"),
    "stocks": (StocksAgent, "stocks"),
    "commodities": (CommoditiesAgent, "commodities"),
    "fx": (FXAgent, "fx"),
}


def build_agents(cfg: dict) -> list:
    agents = []
    for name, (klass, market) in REGISTRY.items():
        acfg = cfg.get("agents", {}).get(name, {})
        if not acfg.get("enabled", True):
            continue
        if not cfg["markets"].get(market, {}).get("enabled", False):
            continue
        agents.append(klass(cfg, acfg))
    return agents
