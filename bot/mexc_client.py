import ccxt.async_support as ccxt

class MexcClient:
    def __init__(self, api_key: str, secret: str, quote: str = "USDT"):
        self.quote = quote
        self.exchange = ccxt.mexc({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
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

    async def get_portfolio(self) -> dict:
        """Returns {symbol: {'amount': x, 'value_usdt': y}} and total_usdt"""
        balance = await self.exchange.fetch_balance()
        portfolio = {}
        total_usdt = 0.0

        for sym, data in balance["total"].items():
            amount = float(data or 0)
            if amount < 1e-8:
                continue
            if sym == self.quote:
                portfolio[sym] = {"amount": amount, "value_usdt": amount, "price": 1.0}
                total_usdt += amount
                continue
            try:
                ticker = await self.exchange.fetch_ticker(f"{sym}/{self.quote}")
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price > 0:
                    val = amount * price
                    portfolio[sym] = {"amount": amount, "value_usdt": val, "price": price}
                    total_usdt += val
            except Exception:
                continue

        return portfolio, total_usdt

    async def execute_rebalance(self, trades: list) -> list:
        """trades: [{'symbol': 'BTC', 'action': 'buy'/'sell', 'usdt_amount': 50}]"""
        results = []
        for trade in trades:
            sym = trade["symbol"]
            action = trade["action"]
            usdt_amt = trade["usdt_amount"]
            try:
                ticker = await self.exchange.fetch_ticker(f"{sym}/{self.quote}")
                price = float(ticker["last"])
                qty = usdt_amt / price
                market = await self.exchange.fetch_markets()
                min_qty = 0.0
                for m in market:
                    if m["symbol"] == f"{sym}/{self.quote}":
                        min_qty = m.get("limits", {}).get("amount", {}).get("min", 0) or 0
                        break
                if qty < min_qty:
                    results.append({"symbol": sym, "action": action, "status": "skip",
                                    "reason": f"الكمية أقل من الحد ({min_qty})"})
                    continue
                if action == "sell":
                    order = await self.exchange.create_market_sell_order(f"{sym}/{self.quote}", qty)
                else:
                    order = await self.exchange.create_market_buy_order(f"{sym}/{self.quote}", qty)
                results.append({"symbol": sym, "action": action, "status": "ok",
                                "usdt": usdt_amt, "price": price, "order_id": order.get("id")})
            except Exception as e:
                results.append({"symbol": sym, "action": action, "status": "error",
                                "reason": str(e)[:100]})
        return results

    async def close(self):
        await self.exchange.close()
