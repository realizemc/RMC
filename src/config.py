"""Loads config.yaml into a plain, typed-ish namespace."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(REPO_ROOT, "config.yaml")


@dataclass
class AccountConfig:
    portfolio_value: float
    max_risk_per_trade_pct: float
    max_open_positions: int
    max_trade_cost_usd: float
    max_correlation: float
    confidence_size_floor_pct: float


@dataclass
class StrategyConfig:
    min_dte: int
    max_dte: int
    long_leg_delta_min: float
    long_leg_delta_max: float
    short_leg_delta_min: float
    short_leg_delta_max: float
    rsi_period: int
    rsi_bull_min: float
    rsi_bull_max: float
    rsi_bear_min: float
    rsi_bear_max: float
    sma_fast: int
    sma_slow: int
    iv_rank_max_pct: float
    min_open_interest: int
    min_volume: int
    max_bid_ask_spread_pct: float
    avoid_earnings: bool


@dataclass
class ExitsConfig:
    profit_target_pct: float
    stop_loss_pct: float
    exit_rule_mode: str
    close_by_dte: int
    theta_pct_of_value: float


@dataclass
class DataConfig:
    price_history_period: str
    cache_dir: str


@dataclass
class AlertsConfig:
    log_dir: str
    write_markdown: bool


@dataclass
class NotificationsConfig:
    enabled: bool
    to_email: str
    include_position_checks: bool
    send_on_empty: bool
    include_hot_list: bool


@dataclass
class MostActiveConfig:
    top_n: int
    universe: list


@dataclass
class Config:
    account: AccountConfig
    watchlist: list
    strategy: StrategyConfig
    exits: ExitsConfig
    data: DataConfig
    alerts: AlertsConfig
    notifications: NotificationsConfig
    most_active: MostActiveConfig
    path: str = field(default=DEFAULT_CONFIG_PATH)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Config:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    cfg = Config(
        account=AccountConfig(**raw["account"]),
        watchlist=list(raw["watchlist"]),
        strategy=StrategyConfig(**raw["strategy"]),
        exits=ExitsConfig(**raw["exits"]),
        data=DataConfig(**raw["data"]),
        alerts=AlertsConfig(**raw["alerts"]),
        notifications=NotificationsConfig(**raw["notifications"]),
        most_active=MostActiveConfig(**raw["most_active"]),
        path=path,
    )

    cache_dir = os.path.join(REPO_ROOT, cfg.data.cache_dir)
    log_dir = os.path.join(REPO_ROOT, cfg.alerts.log_dir)
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    return cfg
