import asyncio

from uniwatch.db import db
from uniwatch.models import Exchange, Event, Token
from uniwatch.config import config
from uniwatch import debug

from uniswap.factory import uniswap
from uniswap import abi

from tqdm import trange
from web3.auto import w3
from web3.utils.events import get_event_data
from eth_utils import event_abi_to_log_topic, encode_hex


topics_to_abi = {event_abi_to_log_topic(x): x for x in abi.exchange if x['type'] == 'event'}
topic_filter = [encode_hex(x) for x in topics_to_abi]


def decode_logs(logs):
    return [
        get_event_data(topics_to_abi[log['topics'][0]], log)
        for log in logs
    ]


def filter_params(address, from_block=None, to_block=None):
    return {
        'address': address,  # many addresses possible
        'fromBlock': from_block or config.genesis,
        'toBlock': to_block or 'latest',
        'topics': [topic_filter]
    }


async def get_exchanges() -> [Exchange]:
    last = await db.fetchval('select max(block) + 1 from exchanges') or uniswap.genesis
    new_exchanges = [
        Exchange.from_log(log) for log in
        uniswap.events.NewExchange.createFilter(fromBlock=last).get_all_entries()
    ]
    for exchange in new_exchanges:
        await exchange.save()
    exchanges = await db.fetch('select token, exchange, block from exchanges')
    return [Exchange(*row) for row in exchanges]


async def index_tokens(exchanges):
    for exchange in exchanges:
        ex = uniswap.get_exchange(exchange.token)
        token = Token(token=exchange.token, symbol=ex.token.symbol, name=ex.token.name, decimals=ex.token.decimals)
        await token.save()


async def index_exchange_logs(exchange: Exchange, step=4096):
    market = uniswap.get_exchange(exchange.token)
    print(market)
    sql = 'select last_block + 1 from exchanges where exchange = $1'
    start = await db.fetchval(sql, exchange.exchange) or exchange.block
    last = w3.eth.blockNumber
    for offset in trange(start, last, step):
        to_block = min(offset + step - 1, last)
        params = filter_params(exchange.exchange, from_block=offset, to_block=to_block)
        batch = w3.eth.getLogs(params)
        decoded = decode_logs(batch)
        events = [Event.from_log(log) for log in decoded]
        for event in events:
            await event.save()
        await exchange.update_last_block(to_block)


async def main():
    await db.init()
    exchanges = await get_exchanges()
    await index_tokens(exchanges)
    for i, e in enumerate(exchanges, 1):
        print(i, e)
        await index_exchange_logs(e)


'''
+1. get exchanges
+2. fill logs in batches
3. main loop
4. watch new exchanges
5. watch new blocks
'''
if __name__ == "__main__":
    asyncio.run(main())
