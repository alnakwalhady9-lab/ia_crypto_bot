import requests
import time

def get_btc_price():
    url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"

    try:
        response = requests.get(url, timeout=10)

        # التأكد من نجاح الاتصال
        response.raise_for_status()

        data = response.json()

        # استخراج السعر
        price = data["data"]["amount"]
        currency = data["data"]["currency"]

        return price, currency

    except requests.exceptions.RequestException as error:
        print("حدث خطأ في الاتصال بـ Coinbase:")
        print(error)
        return None, None

    except (KeyError, TypeError, ValueError):
        print("حدث خطأ أثناء قراءة البيانات من Coinbase.")
        return None, None


# تشغيل البوت باستمرار
while True:
    price, currency = get_btc_price()

    if price is not None:
        print("------------------------------")
        print("Bitcoin Current Price")
        print("------------------------------")
        print(f"BTC/USD: {price} {currency}")
        print("------------------------------")

    time.sleep(60)
