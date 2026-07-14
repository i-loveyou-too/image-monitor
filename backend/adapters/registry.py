from adapters.auction import AuctionAdapter
from adapters.cjonstyle import CjOnstyleAdapter
from adapters.elevenst import ElevenStAdapter
from adapters.generic import GenericAdapter
from adapters.gsshop import GsShopAdapter
from adapters.smartstore import SmartstoreAdapter

# 전용 어댑터를 추가하면 이 리스트 맨 앞쪽에 등록 (구체적인 것부터 먼저 매칭되도록).
# 예: ADAPTERS = [SmartstoreAdapter(), CoupangAdapter(), GenericAdapter()]
ADAPTERS = [
    ElevenStAdapter(),
    GsShopAdapter(),
    CjOnstyleAdapter(),
    AuctionAdapter(),
    SmartstoreAdapter(),
    GenericAdapter(),
]


def get_adapter_for_url(url: str):
    for adapter in ADAPTERS:
        if adapter.match_url(url):
            return adapter
    raise ValueError(f"No adapter found for url: {url}")
