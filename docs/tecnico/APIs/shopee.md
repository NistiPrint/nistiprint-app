# WEBHOOKS

## Notificação de pedido

```
{
  "msg_id": "64ca21a1542dfa1148325c4e47e9da00",
  "data": {
    "completed_scenario": "NORMAL",
    "ordersn": "260605AUHAT90E",
    "status": "COMPLETED",
    "update_time": 1781406305
  },
  "shop_id": 376221706,
  "code": 3,
  "timestamp": 1781406306
}
```

## Notificação de mensagem

**webchat_push** (Shopee Push Mechanism)
**Last Updated:** 18 Apr 2025

### Basics

| Property                          | Value                                                                  |
| --------------------------------- | ---------------------------------------------------------------------- |
| Category                          | Webchat Push                                                           |
| Push Mechanism Name               | webchat_push                                                           |
| Push Mechanism Code               | 10                                                                     |
| Push Mechanism Description        | Get the chat message                                                   |
| Push Mechanism Subscription Rules | Seller In House System / Customer Service / Original / Ads Service App |
| Time Out Seconds                  | 2s                                                                     |
| Sequence Guaranteed               | Yes                                                                    |
| Can Repeated Same Message         | Yes                                                                    |
| Retry Seconds                     | 1s, 2s, 3s                                                             |

---

### Push Parameters

| Name                                                                       | Type           | Sample / Notes                                               | Description                                                                                                                                                 |
| -------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| data                                                                       | object         |                                                              | Main payload                                                                                                                                                |
| └─ type                                                                  | string         | notification / message                                       | Type of push                                                                                                                                                |
| └─ region                                                                | string         |                                                              | Region info                                                                                                                                                 |
| └─ content                                                               | object         |                                                              | Detailed message content                                                                                                                                    |
| &nbsp;&nbsp;&nbsp;└─ user_id                                             | string         |                                                              | Returned when`type = notification`                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ conversation_id                                     | string         |                                                              | Shopee's unique identifier for a conversation                                                                                                               |
| &nbsp;&nbsp;&nbsp;└─ type                                                | string         |                                                              | Returned when`type = notification`                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ timestamp                                           | timestamp      |                                                              | Returned when`type = notification`                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ msg_id                                              | int64          |                                                              | Returned when`type = notification`                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ biz_id                                              | int64          |                                                              | Returned when`type = notification`                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ message_id                                          | string         |                                                              | Returned when`type = message`. Unique message ID                                                                                                          |
| &nbsp;&nbsp;&nbsp;└─ shop_id                                             | int64          |                                                              | Returned when`type = message`. Shop that receives the message (`to_shop_id`)                                                                            |
| &nbsp;&nbsp;&nbsp;└─ request_id                                          | string         |                                                              | Returned when`type = message`. For error tracking                                                                                                         |
| &nbsp;&nbsp;&nbsp;└─ from_user_name                                      | string         |                                                              | Sender username                                                                                                                                             |
| &nbsp;&nbsp;&nbsp;└─ from_id                                             | int64          |                                                              | Sender user ID                                                                                                                                              |
| &nbsp;&nbsp;&nbsp;└─ to_id                                               | int64          |                                                              | Recipient user ID                                                                                                                                           |
| &nbsp;&nbsp;&nbsp;└─ to_user_name                                        | string         |                                                              | Recipient username                                                                                                                                          |
| &nbsp;&nbsp;&nbsp;└─ message_type                                        | string         | text / video / image / item / faq_liveagent / bundle_message | Message type                                                                                                                                                |
| &nbsp;&nbsp;&nbsp;└─ content                                             | object         |                                                              | Actual message body (varies by`message_type`)                                                                                                             |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ text                              | string         |                                                              | For`text` or `faq_liveagent`                                                                                                                            |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ translation                       | object         |                                                              | For`text` messages                                                                                                                                        |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ text            | string         |                                                              | Translated text                                                                                                                                             |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ source          | string         |                                                              |                                                                                                                                                             |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ target_language | string         |                                                              |                                                                                                                                                             |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ source_language | string         |                                                              |                                                                                                                                                             |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ mid                               | object         |                                                              | For`text` messages (similar structure to translation)                                                                                                     |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ url                               | string         |                                                              | For`image`                                                                                                                                                |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ thumb_url                         | string         |                                                              | For`image` or `video`                                                                                                                                   |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ thumb_height                      | int64          |                                                              | For`image` or `video`                                                                                                                                   |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ thumb_width                       | int64          |                                                              | For`image` or `video`                                                                                                                                   |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ file_server_id                    | int64          |                                                              | For`image`                                                                                                                                                |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ video_url                         | string         |                                                              | For`video`                                                                                                                                                |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ duration_seconds                  | int64          |                                                              | For`video`                                                                                                                                                |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ shop_id                           | int64          |                                                              | For`item`                                                                                                                                                 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ item_id                           | int64          |                                                              | For`item`                                                                                                                                                 |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ pass_through_data                 | string         |                                                              | For`faq_liveagent`                                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ messages                                            | string[]       | `["23234234234","234232423"]`                              | For`bundle_message`. List of message_ids in the bundle                                                                                                    |
| &nbsp;&nbsp;&nbsp;└─ shopee_chatbot_replied                              | boolean        | true                                                         | For`bundle_message`. Indicates if Shopee Chatbot was involved. Recommend switching to manual reply if `true`                                            |
| &nbsp;&nbsp;&nbsp;└─ created_timestamp                                   | timestamp      |                                                              | Message creation time                                                                                                                                       |
| &nbsp;&nbsp;&nbsp;└─ region                                              | string         |                                                              | Region of the conversation                                                                                                                                  |
| &nbsp;&nbsp;&nbsp;└─ is_in_chatbot_session                               | boolean        |                                                              | Whether the conversation is in a chatbot session                                                                                                            |
| &nbsp;&nbsp;&nbsp;└─ source_content                                      | object         |                                                              | Extra origin info                                                                                                                                           |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ item_id                           | int            |                                                              | Present when message type = item                                                                                                                            |
| &nbsp;&nbsp;&nbsp;└─ sub_account_id                                      | int64          |                                                              | Sub-account ID that sent the message (0 if main account)                                                                                                    |
| &nbsp;&nbsp;&nbsp;└─ sub_account_name                                    | string         |                                                              | Sub-account name (0 if main account)                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ quoted_msg                                          | object[]       |                                                              | Quoted message info                                                                                                                                         |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ message_id                        | int64 / string |                                                              | ID of the quoted message (empty if none)                                                                                                                    |
| &nbsp;&nbsp;&nbsp;└─ business_type                                       | int32          | 0 or 11                                                      | `0` = buyer ↔ seller`11` = affiliate ↔ seller                                                                                                         |
| &nbsp;&nbsp;&nbsp;└─ to_shop_id                                          | int64          |                                                              | Shop ID that receives the message                                                                                                                           |
| &nbsp;&nbsp;&nbsp;└─ from_shop_id                                        | int64          |                                                              | Shop ID that sends the message                                                                                                                              |
| &nbsp;&nbsp;&nbsp;└─ status                                              | string         |                                                              | Possible values:`normal`, `auto_reply`, `blocked`, `user_chat`, `web_chat`, `censored_whitelist`, `censored_blacklist`, `offwork_autoreply` |
| shop_id                                                                    | int            |                                                              | Shop that receives the push                                                                                                                                 |
| code                                                                       | int            | 10                                                           | Push mechanism code                                                                                                                                         |
| timestamp                                                                  | timestamp      |                                                              | When the push was sent                                                                                                                                      |

---

### Push Contents (Examples)

#### 1. Notification type

```json
{
  "msg_id": null,
  "data": {
    "type": "notification",
    "region": "PH",
    "content": {
      "user_id": 12252079,
      "conversation_id": "4670954831706433",
      "type": "mark_as_replied",
      "content": {
        "conversation_id": "4670954310906433"
      },
      "timestamp": 1719883961,
      "msg_id": 0,
      "biz_id": 0,
      "from_id": 0
    }
  }
}
```

#### 2. Message type – text

```json
{
  "msg_id": "",
  "data": {
    "type": "message",
    "region": "ID",
    "content": {
      "message_id": "2302748948493123953",
      "shop_id": 165103149,
      "request_id": "35f9478b-7482-46eb-a268-8f828fedb673",
      "from_id": 165105353,
      "from_user_name": "vn_cstoreponorogo",
      "to_id": 947151379,
      "to_user_name": "keelatofficial",
      "message_type": "text",
      "content": {
        "text": "Baik kak .. 🤗"
      },
      "conversation_id": "709122092476686867",
      "created_timestamp": 1726044721,
      "region": "ID",
      "is_in_chatbot_session": false,
      "source_content": {},
      "quoted_msg": {
        "message_id": ""
      },
      "sub_account_id": 0,
      "sub_account_name": 0
    }
  },
  "shop_id": 947042923,
  "code": 10,
  "timestamp": 1726044722
}
```

#### 3. Message type – video

```json
{
  "data": {
    "type": "message",
    "region": "VN",
    "content": {
      "message_id": "2165920666211451249",
      "shop_id": 123456789,
      "request_id": "1091617252119662617",
      "from_id": 161057467,
      "from_user_name": "hyhy2606",
      "to_id": 213245905,
      "to_user_name": "sixhd.vn",
      "message_type": "video",
      "content": {
        "video_url": "cf03c9e1fe2c0992cdb51c3cb6eab2bd",
        "thumb_url": "6c710d7679c9f3a9a7287250421d17d3_dynamic_tn",
        "thumb_width": 399,
        "thumb_height": 713,
        "duration_seconds": 15
      },
      "conversation_id": "691736553754845137",
      "created_timestamp": 1660799912,
      "region": "VN",
      "is_in_chatbot_session": false,
      "source_content": {},
      "quoted_msg": {
        "message_id": ""
      },
      "sub_account_id": 0,
      "sub_account_name": 0
    }
  },
  "shop_id": 123456789,
  "code": 10,
  "timestamp": 1660799912
}
```

#### 4. Message type – image

```json
{
  "data": {
    "type": "message",
    "region": "VN",
    "content": {
      "message_id": "2165920671942967665",
      "shop_id": 123456789,
      "request_id": "313F2D/BTMessage/p108",
      "from_id": 679422730,
      "from_user_name": "thutrang290402",
      "to_id": 6343861,
      "to_user_name": "thanhnga_hcm",
      "message_type": "image",
      "content": {
        "url": "https://cf.shopee.vn/file/09591ecdc9f1dc7bd507817797d826fe_dynamic",
        "thumb_url": "b9591ecdc9f1dc7bd507817797d826fe_dynamic_tn",
        "thumb_height": 711,
        "thumb_width": 400,
        "file_server_id": 0
      },
      "conversation_id": "27246676204792586",
      "created_timestamp": 1660799915,
      "region": "VN",
      "is_in_chatbot_session": false,
      "source_content": {},
      "quoted_msg": {
        "message_id": ""
      },
      "sub_account_id": 0,
      "sub_account_name": 0
    }
  },
  "shop_id": 123456789,
  "code": 10,
  "timestamp": 1660799915
}
```

#### 5. Message type – item

```json
{
  "data": {
    "type": "message",
    "region": "ID",
    "content": {
      "message_id": "2165920670806327665",
      "shop_id": 123456789,
      "request_id": "389465101372418716",
      "from_id": 163219823,
      "from_user_name": "fadlyjo.",
      "to_id": 119159078,
      "to_user_name": "zhousijia",
      "message_type": "item",
      "content": {
        "shop_id": 109157255,
        "item_id": 9112503530
      },
      "conversation_id": "511784343194732911",
      "created_timestamp": 1660799914,
      "region": "ID",
      "is_in_chatbot_session": false,
      "quoted_msg": {
        "message_id": ""
      },
      "sub_account_id": 0,
      "sub_account_name": 0,
      "source_content": {
        "item_id": 4112503530
      }
    }
  },
  "shop_id": 123456789,
  "code": 10,
  "timestamp": 1660799915
}
```

#### 6. Message type – faq_liveagent

```json
{
  "data": {
    "type": "message",
    "region": "ID",
    "content": {
      "message_id": "2165920670296736113",
      "shop_id": 123456789,
      "request_id": "4600339818579251427",
      "from_id": 172765311,
      "from_user_name": "bundhakevinabizar",
      "to_id": 94311357,
      "to_user_name": "madamegieofficial",
      "message_type": "faq_liveagent",
      "content": {
        "text": "Chat dengan Penjual",
        "pass_through_data": ""
      },
      "conversation_id": "405064194129145983",
      "created_timestamp": 1660799914,
      "region": "ID",
      "is_in_chatbot_session": false,
      "quoted_msg": {
        "message_id": ""
      },
      "sub_account_id": 0,
      "sub_account_name": 0,
      "source_content": {
        "order_sn": "220818EGS328B9"
      }
    }
  },
  "shop_id": 123456789,
  "code": 10,
  "timestamp": 1660799915
}
```

---

### Update Log

| Date       | Update Details                                                                                                                                                                    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2025-04-18 | Add`from_shop_id`, `to_shop_id`, `status`                                                                                                                                   |
| 2024-11-05 | Add`business_type` for affiliate marketing solution chatAdd `bundle_message` for FAQ and chatbot messageAdd `shopee_chatbot_replied` to indicate if Shopee Chatbot involved |
| 2024-09-23 | Add`sub_account_id` and `sub_account_name`Add `quoted_msg`                                                                                                                  |
| 2024-09-04 | Update the definition of the`shop_id` inside `content`                                                                                                                        |
| 2022-09-24 | Roll back retry config                                                                                                                                                            |

---

**Notes for LLM use**

- Two main payload types: `notification` and `message`.
- `message_type` determines the structure of `content`.
- `business_type`: `0` = buyer-seller, `11` = affiliate-seller.
- When `shopee_chatbot_replied = true` (in `bundle_message`), it is recommended to switch to manual reply mode.
- Pagination / sequencing is guaranteed; retries occur at 1s, 2s, 3s.

# API

## v2.order.get_order_detail

**GET** /api/v2/order/get_order_detail Use this api to get order detail.

### Request Parameters

| Name                         | Type    | Required | Sample                        | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ---------------------------- | ------- | -------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| order_sn_list                | string  | True     | 201214JAJXU6G7,201214JASXYXY6 | The set of order_sn. If there are multiple order_sn, you need to use English comma to connect them. limit [1,50]                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| request_order_status_pending | boolean | False    | true                          | Compatible parameter during migration period, send True will let API support PENDING status and return  pending_terms, send False or don’t send will fallback to old logic                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| response_optional_fields     | string  | False    | total_amount                  | a response fields you want to get. Please select from the below response parameters. If you input an object field, all the params under it will be included automatically in the response. If there are multiple response fields you want to get, you need to use English comma to connect them. Available values: buyer_user_id,buyer_username,estimated_shipping_fee,recipient_address,actual_shipping_fee ,goods_to_declare,note,note_update_time,item_list,pay_time,dropshipper, dropshipper_phone,split_up,buyer_cancel_reason,cancel_by,cancel_reason,actual_shipping_fee_confirmed,buyer_cpf_id,fulfillment_flag,pickup_done_time,package_list,shipping_carrier,payment_method,total_amount,buyer_username,invoice_data,order_chargeable_weight_gram,return_request_due_date,edt,payment_info,international_label |

### Response Example

```
{
  {
    "error": "",
    "message": "",
    "request_id": "023c50ace933ba38473a5fb2a7dc8821",
    "response": {
        "order_list": [
            {
                "actual_shipping_fee_confirmed": true,
                "buyer_cancel_reason": "",
                "buyer_cpf_id": null,
                "buyer_user_id": 1170319091,
                "buyer_username": "xt4fdsf96j",
                "cancel_by": "",
                "cancel_reason": "",
                "cod": true,
                "create_time": 1712601591,
                "currency": "VND",
                "days_to_ship": 2,
                "dropshipper": null,
                "dropshipper_phone": null,
                "estimated_shipping_fee": 5000,
                "fulfillment_flag": "fulfilled_by_local_seller",
                "goods_to_declare": false,
                "invoice_data": null,
                "item_list": [
                    {
                        "add_on_deal": false,
                        "add_on_deal_id": 0,
                        "image_info": {
                            "image_url": "https://cf.shopee.vn/file/vn-11134207-7qukw-lf6guphtf6oad3_tn"
                        },
                        "is_b2c_owned_item": false,
                        "is_prescription_item": false,
                        "item_id": 23620853561,
                        "item_name": "🦋giảm giá🦋Kem nở ngực SADOER enlarging breast cream Papaya / Coconut essence 60g Chiết xuất đu đủ, cùi dừa, nở ngực, kem nâng ngực nhanh",
                        "item_sku": "",
                        "main_item": false,
                        "model_discounted_price": 48000,
                        "model_id": 221404189791,
                        "model_name": "60g（Papaya）",
                        "model_original_price": 300000,
                        "model_quantity_purchased": 1,
                        "model_sku": "QAZ-SADOER-05",
                        "order_item_id": 23620853561,
                        "product_location_id": [
                            "VN10XX2UZ"
                        ],
                        "promotion_group_id": 0,
                        "promotion_id": 779222207758537,
                        "promotion_type": "flash_sale",
                        "weight": 0.01,
                        "wholesale": false
                    }
                ],
                "message_to_seller": "",
                "note": "",
                "note_update_time": 0,
                "order_sn": "2404098R48U37H",
                "order_status": "COMPLETED",
                "package_list": [
                    {
                        "group_shipment_id": null,
                        "item_list": [
                            {
                                "item_id": 23620853561,
                                "model_id": 221404189791,
                                "model_quantity": 1,
                                "order_item_id": 23620853561,
                                "product_location_id": "VN10XX2UZ",
                                "promotion_group_id": 0
                            }
                        ],
                        "logistics_status": "LOGISTICS_DELIVERY_DONE",
                        "package_number": "OFG166300791210964",
                        "parcel_chargeable_weight_gram": 10,
                        "shipping_carrier": "5-Day Delivery (SPX)",
                        "logistics_channel_id": 18080
                        "allow_self_design_awb": true,
			"sorting_group": "North"
                    }
                ],
                "pay_time": 1712817766,
                "payment_method": "Cash on Delivery",
                "pickup_done_time": 1712726577,
                "recipient_address": {
                    "city": "Huyện Phước Long",
                    "district": "Xã Phong Thạnh Tây B",
                    "full_address": "Ấp******",
                    "name": "P******n",
                    "phone": "******64",
                    "region": "VN",
                    "state": "Bạc Liêu",
                    "town": "",
                    "zipcode": ""
                },
                "region": "VN",
                "reverse_shipping_fee": 0,
                "ship_by_date": 1712671200,
                "shipping_carrier": "Giao Hàng Nhanh",
                "split_up": false,
                "total_amount": 32119,
                "update_time": 1713139948
            }
        ]
    }
}
```

### Error Codes

| Error            | Error Description                                   |
| ---------------- | --------------------------------------------------- |
| error_not_found  | Wrong parameters, detail: {msg}.                    |
| error_param      | Wrong parameters, detail: {msg}.                    |
| error_permission | Sorry you don't have the permission, detail: {msg}. |
| error_server     | System error. Please try again later.               |
| error_param      | There is no access_token in query.                  |
| error_auth       | Invalid access_token.                               |
| error_param      | Invalid partner_id.                                 |
| error_param      | There is no partner_id in query.                    |
| error_auth       | No permission to current api.                       |
| error_param      | There is no sign in query.                          |
| error_sign       | Wrong sign.                                         |
| error_param      | no timestamp                                        |
| error_param      | Invalid timestamp                                   |
| error_network    | Inner http call failed                              |
| error_data       | parse data failed                                   |
| error_data       | data not exist                                      |
| error_param      | parameter invalid                                   |
| error_param      | The information you queried is not found.           |
| error_param      | Wrong parameters, detail: {msg}.                    |
| error_server     | Something wrong. Please try later.                  |
| error_shop       | shopid is invalid                                   |
| error_param      | request not from gateway                            |

## **v2.sellerchat.get_message** (Shopee Open Platform API V2)

### Overview

Retrieves messages from a seller chat conversation.

---

### Request

#### Request Address

```
GET /api/v2/sellerchat/get_message
```

#### Common Request Parameters

| Parameter    | Type   | Required | Description  |
| ------------ | ------ | -------- | ------------ |
| partner_id   | int    | Yes      | Partner ID   |
| timestamp    | int    | Yes      | Timestamp    |
| access_token | string | Yes      | Access token |
| shop_id      | int    | Yes      | Shop ID      |
| sign         | string | Yes      | Signature    |

#### Request Parameters

| Parameter       | Type     | Required | Description                                                                            |
| --------------- | -------- | -------- | -------------------------------------------------------------------------------------- |
| conversation_id | string   | Yes      | Shopee conversation ID                                                                 |
| offset          | string   | No       | The oldest message ID (for pagination). Use the`next_offset` from previous response. |
| page_size       | int32    | No       | Number of messages to return (default/max limits apply per platform rules).            |
| message_id_list | string[] | No       | List of specific message IDs to retrieve.                                              |
| business_type   | int      | No       | Differentiate seller-buyer chat vs seller-affiliate chat.                              |

#### Request Example

(Not provided in source documentation.)

---

### Response

#### Response Parameters

| Field                                                                | Type      | Description                                                                                                                                                                          |
| -------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| error                                                                | string    | Error code (empty on success)                                                                                                                                                        |
| message                                                              | string    | Error message                                                                                                                                                                        |
| request_id                                                           | string    | Request ID                                                                                                                                                                           |
| response                                                             | object    | Main response body                                                                                                                                                                   |
| └─ messages                                                        | object[]  | List of messages                                                                                                                                                                     |
| &nbsp;&nbsp;&nbsp;└─ message_id                                    | string    | Message ID                                                                                                                                                                           |
| &nbsp;&nbsp;&nbsp;└─ message_type                                  | string    | Message type (text, image, video, sticker, etc.)                                                                                                                                     |
| &nbsp;&nbsp;&nbsp;└─ from_id                                       | int64     | Sender ID                                                                                                                                                                            |
| &nbsp;&nbsp;&nbsp;└─ from_user_name                                | string    | Sender username                                                                                                                                                                      |
| &nbsp;&nbsp;&nbsp;└─ to_id                                         | int64     | Recipient ID                                                                                                                                                                         |
| &nbsp;&nbsp;&nbsp;└─ to_user_name                                  | string    | Recipient username                                                                                                                                                                   |
| &nbsp;&nbsp;&nbsp;└─ created_timestamp                             | timestamp | Creation time                                                                                                                                                                        |
| &nbsp;&nbsp;&nbsp;└─ region                                        | string    | Region                                                                                                                                                                               |
| &nbsp;&nbsp;&nbsp;└─ status                                        | string    | Status (`normal`, `auto_reply`, `blocked`, `user_chat`, `web_chat`, `censored_whitelist`, `censored_blacklist`, `offwork_autoreply`)                                 |
| &nbsp;&nbsp;&nbsp;└─ source                                        | string    | Source (`old_webchat`, `new_webchat`, `ios`, `android`, `push`, `crm`, `mini_webchat`, `pc_mall_minichat`, `mweb`, `openapi`, `chatbot`, `proactive_update`) |
| &nbsp;&nbsp;&nbsp;└─ content                                       | object    | Message content                                                                                                                                                                      |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ text                        | string    | Text content (for text messages)                                                                                                                                                     |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ url / image_url / video_url | string    | Media URLs depending on type                                                                                                                                                         |
| &nbsp;&nbsp;&nbsp;└─ message_option                                | int       | (Meaningless / reserved)                                                                                                                                                             |
| &nbsp;&nbsp;&nbsp;└─ source_content                                | object    | Additional origin details                                                                                                                                                            |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ order_sn                    | string    | Related order SN (if applicable)                                                                                                                                                     |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└─ item_id                     | int64     | Related product ID (if applicable)                                                                                                                                                   |
| └─ page_result                                                     | object    | Pagination info                                                                                                                                                                      |
| &nbsp;&nbsp;&nbsp;└─ next_offset                                   | string    | Oldest message ID for next page                                                                                                                                                      |
| &nbsp;&nbsp;&nbsp;└─ page_size                                     | int32     | Number of messages returned                                                                                                                                                          |

#### Response Example

(No Response Example Set.)

---

### Error Codes

#### Business Error Codes

| Error                 | Description                                                                                                                | Details / Guidance |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| error_network         | Inner http call failed                                                                                                     | —                 |
| error_data            | parse data failed / data not exist                                                                                         | —                 |
| error_param           | parameter invalid / Wrong parameters, detail: {msg} / The information you queried is not found. / request not from gateway | —                 |
| internal_server_error | Server error from system. Please retry later.                                                                              | —                 |
| error_server          | Something wrong. Please try later.                                                                                         | —                 |
| error_shop            | shopid is invalid                                                                                                          | —                 |
| not_open_market       | Market is not open.                                                                                                        | —                 |
| param_error           | Error or loss in request parameter.                                                                                        | —                 |
| resource_not_found    | The request parameter could not be found.                                                                                  | —                 |
| system_busy           | System is busy now. Please decrease the QPS then retry later.                                                              | —                 |
| user_is_unauthorized  | Missing authorization information.                                                                                         | —                 |

#### Common Error Codes

| Error                      | Description                                                                                                                                                                                                                                                                                                          |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| error_auth                 | partner_id is invalid / The App is deleted... / App developer’s permissions... / No permission to current api / Invalid access_token / Invalid partner_id or shopid / System error...                                                                                                                               |
| error_param                | There is no partner_id in query / Invalid partner_id / no timestamp / Invalid timestamp / There is no sign in query / Permission denied... / Partner_id is invalid... / no timestamp / Timestamp is invalid... / Timestamp is expired / There is no access_token... / There is no shop_id... / shop_id is invalid... |
| error_sign                 | Wrong sign.                                                                                                                                                                                                                                                                                                          |
| invalid_partner_id         | Invalid partner_id, please have a check.                                                                                                                                                                                                                                                                             |
| error_api_call_restricted  | The App permission for api call have been restricted...                                                                                                                                                                                                                                                              |
| api_suspended              | The API is offline. Please call v2 API instead.                                                                                                                                                                                                                                                                      |
| error_limit                | Daily API call limit reached. Retry after 00:00 (UTC+08:00).                                                                                                                                                                                                                                                         |
| error_rate_limit           | Too many requests. Rate limit reached.                                                                                                                                                                                                                                                                               |
| source_ip_undeclared       | Request Source IP is undeclared. Declare in Console > App list > IP Address Whitelist.                                                                                                                                                                                                                               |
| error_partner_key_expired  | API partner key expired. Reset Live API Partner Key.                                                                                                                                                                                                                                                                 |
| error_api_permission       | This app type has no permission to this API.                                                                                                                                                                                                                                                                         |
| shop_no_linked             | Partner and shop has no linked.                                                                                                                                                                                                                                                                                      |
| shop_banned                | Shop account banned.                                                                                                                                                                                                                                                                                                 |
| invalid_acceess_token      | Invalid access_token.                                                                                                                                                                                                                                                                                                |
| partner_shop_no_link       | Invalid partner_id or shop_id.                                                                                                                                                                                                                                                                                       |
| error_ashop_api_permission | Affiliate shop has no permission.                                                                                                                                                                                                                                                                                    |
| error_kyc_auth             | Complete Seller Registration on Shopee Seller Center first.                                                                                                                                                                                                                                                          |

#### Error Example

(No Error Example Set.)

---

### API Permissions

APP types that can call this API:

- Seller In House System
- Customer Service

---

### API Tools

- API Test Tools
- API Access Log

---

### Update Log

| Date       | Update Details                                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| 2025-12-25 | the format of "user_id" update to 'int64'                                                                                 |
| 2024-10-30 | Add business_type to differentiate seller buyer chat and seller affiliate chat                                            |
| 2024-06-21 | add "messages" response parameter. Indicates message id list included in bundle message                                   |
| 2023-03-13 | add get_message_list in request; add video_url for video type message; add image_url for sticker type message in response |
| 2022-11-11 | update                                                                                                                    |

---

**Notes for LLM use:**

- This is a clean, structured extraction of the official Shopee documentation for `v2.sellerchat.get_message`.
- Pagination uses `offset` / `next_offset` (message IDs).
- Content structure varies by `message_type` (text, image, video, sticker, etc.).
- Always include common parameters (`partner_id`, `timestamp`, `access_token`, `shop_id`, `sign`) in every call.
