# Shopee

## Push Mechanism notifications

**Subscribing to Shopee Open Platform Push Mechanism helps you get immediate notifications when a specific event occurs. This lets you receive timely updates without having to periodically poll the API endpoint.**

**⚠️** **Note:** **Push Mechanism** **on the Shopee Open Platform Console is equivalent to what’s commonly known as webhooks.**

**Here’s an overview of how Push Mechanism works on Shopee Open Platform:**

1. **You subscribe to a specific push type for your App and define a callback URL.**
2. **The specific event, such as an order status update, happens.**
3. **Shopee sends an HTTP POST request to the defined callback URL.**
4. **You receive a notification via your defined callback URL.**

**⚠️** **Note: Push Mechanism (webhooks) on Shopee Open Platform only notifies you that data for the specific event has changed. To get more updated information, make a call to the corresponding API. You’re encouraged to use both to enhance your systems’ integration efficiency.**


## Push Authorization

**To prevent cyberattacks, we have provided an authorization signature for each Push request, which can be located in the** **Authorization** **field of the HTTP request header. With this, you can identify Shopee's authorization information.**

**This step is technically optional, but we strongly recommend that developers use the following steps to validate the request to generate the authorization signature, ensuring that it matches the authorization signature generated from the Push request. Here's how you can generate the signature:**

**1. Use URL, |, response.content as the signature base string. E.g:**

**‘http://www.example.com/example/uri|{“shop_id”: 123, “code”: 1, “success”: 1, “extra”: “shop_id 123 is authorized successfully”, “data”: {“more_info”: “more info”}, “timestamp”: 1470198856}’**

**Note that the json.loads(response.content) method is not recommended**

**2. Retrieve your partner key from your App details on Shopee Open Platform Console**

**3. Use the signature base string and partner key to generate the signature with the HMAC-SHA256 hashing algorithm. The output of the HMAC signature function is a binary string. This requires hex encoding to generate the signature string.**

**Code demo**

**Python:**

```


import hmac

def verify_push_msg(url, request_body, partner_key, authorization):

    base_string = url + '|' + request_body

    cal_auth = hmac.new(partner_key, base_string, hashlib.sha256).hexdigest()

    if cal_auth != authorization:

        return False

    else:

        return True
```


## Push Mechanism Retry Logic

**To avoid receiving repeated notifications from Push Mechanism, set up your callback URL to respond according to these HTTP response requirements:**

* **Includes a status code of 2xx.**
* **Includes an empty body.**

**⚠️** **Note: All Pushes (webhooks) support a different maximum number of notifications and intervals for any repeated notifications. See the next section** **Push Mechanism Warning/Disable Logic** **for Apps that have a poor success rate for responding to notifications.**
