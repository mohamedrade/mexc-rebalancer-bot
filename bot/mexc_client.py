import ccxt.async_support as ccxt

# Minimum USD value to consider an asset worth pricing
_MIN_VALUE_THRESHOLD = 0.5

class MexcClient:
    def __init__(self, api_key: str, secret: str, quote: str = "USDT"):
        self.quote = quote
        self.exchange = ccxt.mexc({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "timeout": 10000,  # 10s per request
            "options": {"defaultType": "spot"},
        })

    async def validate_credentials(self) -> tuple:
        try:
            await self.exchange.fetch_balance()
            return True, "OK"
        except ccxt.AuthenticationError as e:
            return False, f"مفاتيح خاطئة: {str(e)[:80]}"
        except Exception as e:
            return False, str(e)[:100]

    async def get_portfolio(self) -> tuple:
        """Returns ({symbol: {amount, value_usdt, price}}, total_usdt)"""
        balance = await self.exchange.fetch_balance()
        total_usdt = 0.0
        portfolio = {}
        holdings = {}

        for sym, amount in balance["total"].items():
            amount = float(amount or 0)
            if amount < 1e-8:
                continue
            if sym == self.quote:
                portfolio[sym] = {"amount": amount, "value_usdt": amount, "price": 1.0}
                total_usdt += amount
            else:
                holdings[sym] = amount

        if not holdings:
            return portfolio, total_usdt

        # Only fetch tickers for assets that could be worth something
        # Use a rough filter: skip dust (amount < 0.00001 for most coins)
        pairs = [f"{sym}/{self.quote}" for sym in holdings]

        try:
            tickers = await self.exchange.fetch_tickers(pairs)
        except Exception:
            # Fallback: fetch one by one only for known holdings
            tickers = {}
            for sym in holdings:
                try:
                    t = await self.exchange.fetch_ticker(f"{sym}/{self.quote}")
                    tickers[f"{sym}/{self.quote}"] = t
                except Exception:
                    pass

        for sym, amount in holdings.items():
            pair = f"{sym}/{self.quote}"
            ticker = tickers.get(pair, {})
            price = float(ticker.get("last") or ticker.get("close") or 0)
            if price <= 0:
                continue
            val = amount * price
            if val < _MIN_VALUE_THRESHOLD:
                continue  # skip dust
            portfolio[sym] = {"amount": amount, "value_usdt": val, "price": price}
            total_usdt += val

        return portfolio, total_usdt

    async def execute_rebalance(self, trades: list) -> list:
        if not trades:
            return []

        pairs = [f"{t['symbol']}/{self.quote}" for t in trades]

        try:
            tickers = await self.exchange.fetch_tickers(pairs)
        except Exception:
            tickers = {}

        try:
            markets = await self.exchange.fetch_markets()
            min_qty_map = {m["symbol"]: m.get("limits", {}).get("amount", {}).get("min", 0) or 0
                           for m in markets}
        except Exception:
            min_qty_map = {}

        results = []
        for trade in trades:
            sym = trade["symbol"]
            action = trade["action"]
            usdt_amt = trade["usdt_amount"]
            pair = f"{sym}/{self.quote}"
            try:
                ticker = tickers.get(pair, {})
                price = float(ticker.get("last") or 0)
                if not price:
                    t = await self.exchange.fetch_ticker(pair)
                    price = float(t.get("last") or 0)
                if not price:
                    raise ValueError("تعذّر جلب السعر")

                qty = usdt_amt / price
                min_qty = min_qty_map.get(pair, 0)
                if qty < min_qty:
                    results.append({"symbol": sym, "action": action, "status": "skip",
                                    "reason": f"الكمية أقل من الحد ({min_qty})"})
                    continue

                if action == "sell":
                    order = await self.exchange.create_market_sell_order(pair, qty)
                else:
                    order = await self.exchange.create_market_buy_order(pair, qty)

                results.append({"symbol": sym, "action": action, "status": "ok",
                                "usdt": usdt_amt, "price": price, "order_id": order.get("id")})
            except Exception as e:
                results.append({"symbol": sym, "action": action, "status": "error",
                                "reason": str(e)[:100]})
        return results

    async def close(self):
        await self.exchange.close()
