from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RouteModel(BaseModel):
    """单段买卖路线的计算结果。"""

    class GoodsData(BaseModel):
        """单个商品的买入、卖出与利润数据。"""

        num: int = 0
        buy_price: int = 0
        sell_price: int = 0
        profit: int = 0

    buy_city_name: str = ""
    sell_city_name: str = ""
    haggle_num: int = 0
    goods_data: Dict[str, GoodsData] = Field(default_factory=dict)
    buy_goods: Dict[str, int] = Field(default_factory=dict)
    buy_price: int = 0
    sell_price: int = 0
    cost: int = 0
    income: int = 0
    profit: int = 0
    city_tired: int = 999
    city_tired_estimated: bool = False
    tired_profit: int = 0
    book_profit: int = 0
    general_profit_index: int = 0
    book: int = -1
    num: int = 0
    last_not_wasting_restock: int = -1


class RoutesModel(BaseModel):
    """双城往返路线的汇总结果。"""

    city_data: List[RouteModel] = Field(default_factory=lambda: [RouteModel(), RouteModel()])
    profit: int = 0
    city_tired: int = 0
    tired_profit: int = 0
    book: int = -1
    general_profit_index: int = 0
    jiaozi_profit: Optional[int] = None
    tiemeng_profit: Optional[int] = None
    jiaozi_general_profit_index: Optional[int] = None
    tiemeng_general_profit_index: Optional[int] = None
    strategy_label: str = ""
