from flask import Flask, render_template, request, jsonify
import logging

# ✅ Import from your package modules
from customerService.user_summary import get_user_summary_by_phone
from customerService.magic_word_summary import get_magicword_requests, get_magicword_detail
from google.cloud import firestore as gfirestore
from firebase_setup import get_project_b_firestore
from datetime import datetime

app = Flask(
    __name__,
    template_folder="customerService/templates"
)

@app.route("/", methods=["GET"])
def landing():
    return render_template("index.html")

@app.route("/user-summary", methods=["GET", "POST"])
def user_summary():
    summary = None
    error = None
    identifier = ""

    if request.method == "POST":
        # ✅ Handle JSON requests (from JavaScript)
        if request.is_json:
            data = request.get_json()
            identifier = data.get("identifier", "").strip()
            
            if not identifier:
                return jsonify({"error": "Please enter phone number or email."}), 400
            
            try:
                summary_result = get_user_summary_by_phone(identifier)
                if not summary_result.get("found"):
                    error_msg = summary_result.get("message") or summary_result.get("error") or "User not found."
                    return jsonify({"error": error_msg}), 404
                
                return jsonify({"summary": summary_result}), 200
            except Exception as e:
                logging.exception("Error while fetching user summary")
                return jsonify({"error": f"Error while fetching data: {e}"}), 500
        
        # ✅ Handle form requests (from HTML form - existing code)
        identifier = request.form.get("identifier", "").strip()

        if not identifier:
            error = "Please enter phone number or email."
        else:
            try:
                summary = get_user_summary_by_phone(identifier)
                if not summary.get("found"):
                    error = summary.get("message") or summary.get("error") or "User not found."
                    summary = None
            except Exception as e:
                logging.exception("Error while fetching user summary")
                error = f"Error while fetching data: {e}"

    return render_template(
        "user_summary.html",
        identifier=identifier,
        summary=summary,
        error=error
    )

@app.route("/magic-word-summary", methods=["GET"])
def magic_word_summary():
    return render_template("magic_word_summary.html")

# ✅ API ENDPOINTS FOR MAGIC WORD REQUESTS
@app.route("/api/magic-words", methods=["GET"])
def api_magic_words():
    """Fetch all pending magic word requests"""
    try:
        limit = int(request.args.get("limit", "100"))
        result = get_magicword_requests(limit=limit)
        return jsonify(result)
    except Exception as e:
        logging.exception("Error fetching magic word requests")
        return jsonify({"found": False, "error": str(e)}), 500

@app.route("/api/magic-words/<magic_word_user_id>", methods=["GET"])
def api_magic_word_detail(magic_word_user_id):
    """Fetch detail for a specific magic word request with chat history"""
    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable
        
        result = get_magicword_detail(magic_word_user_id)
        
        if result.get("found"):
            # ✅ Fetch last 10 messages from chat
            chat_id = result.get("chat", {}).get("id")
            if chat_id:
                try:
                    db = get_project_b_firestore()
                    messages = (
                        db.collection("chats")
                        .document(chat_id)
                        .collection("messages")
                        .order_by("created_at", direction=gfirestore.Query.DESCENDING)
                        .limit(10)
                        .get()
                    )
                    
                    chat_history = []
                    for msg_doc in reversed(messages):  # reverse to show chronologically
                        msg_data = msg_doc.to_dict() or {}
                        if "created_at" in msg_data:
                            iso = _ts_to_iso(msg_data["created_at"])
                            msg_data["created_at"] = iso
                            msg_data["created_at_readable"] = _iso_to_readable(iso)
                        chat_history.append(msg_data)
                    
                    result["chat_history"] = chat_history
                except Exception as e:
                    logging.warning(f"Error fetching chat history: {e}")
                    result["chat_history"] = []
        
        status_code = 200 if result.get("found") else 404
        return jsonify(result), status_code
    except Exception as e:
        logging.exception("Error fetching magic word detail")
        return jsonify({"found": False, "error": str(e)}), 500

@app.route("/api/magic-words/<magic_word_user_id>/status", methods=["PUT"])
def update_magic_word_status(magic_word_user_id):
    """Update magic word request status and user details"""
    try:
        from customerService.magic_word_summary import (
            create_service_request, 
            send_service_request_message,
            create_service_order,
            send_booking_confirmation_message
        )
        from datetime import datetime
        
        db = get_project_b_firestore()
        
        # Get current status
        magic_doc = db.collection("magicWordUser").document(magic_word_user_id).get()
        if not magic_doc.exists:
            return jsonify({"success": False, "error": "Magic word not found"}), 404
        
        current_data = magic_doc.to_dict()
        current_status = current_data.get("status", "requested")
        chat_id = current_data.get("chatId")
        user_id = current_data.get("userId")
        magic_word = current_data.get("magicWord")
        service_request_id = current_data.get("serviceRequestId")
        
        # Determine next status
        if current_status == "requested":
            new_status = "inProgress"
        elif current_status == "inProgress":
            new_status = "completed"
        else:
            return jsonify({"success": False, "error": "Status cannot be changed"}), 400
        
        # Get booking details from request body
        request_body = request.get_json() or {}
        booking_details = request_body.get("details", {})
        
        # ✅ Get payment status from booking details
        payment_status = booking_details.get("paymentStatus", "pending")
        
        # ✅ Update user details if provided
        if booking_details.get("userId") and booking_details.get("userUpdate"):
            user_update = booking_details.get("userUpdate")
            db.collection("users").document(booking_details.get("userId")).update({
                "firstName": user_update.get("firstName", ""),
                "lastName": user_update.get("lastName", ""),
                "phoneNumber": user_update.get("phoneNumber", ""),
                "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
            })
            logging.info(f"✅ User {booking_details.get('userId')} updated")
            print(f"👤 USER UPDATE: Phone={user_update.get('phoneNumber')}, Name={user_update.get('firstName')} {user_update.get('lastName')}")
        
        # Update status in Firestore
        db.collection("magicWordUser").document(magic_word_user_id).update({
            "status": new_status,
            "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        })
        
        logging.info(f"✅ Magic word {magic_word_user_id} status changed: {current_status} → {new_status}")
        
        # 📝 Create service request when status changes to inProgress
        if new_status == "inProgress":
            print(f"📝 Creating service request with details...")
            print(f"💳 Payment Status: {payment_status}")
            
            sr_result = create_service_request(magic_word_user_id, current_data, booking_details)
            print(f"📝 Service request result: {sr_result}")
            
            if sr_result.get("success"):
                service_request_id = sr_result.get("service_request_id")
                
                # ✅ Check if payment is successful
                if payment_status == "success":
                    print(f"✅ PAYMENT SUCCESS - Creating service order...")
                    
                    # 🎫 Create booking order immediately
                    order_result = create_service_order(
                        magic_word_user_id, 
                        service_request_id,
                        booking_details
                    )
                    print(f"🎫 Order result: {order_result}")
                    
                    if order_result.get("success"):
                        # ✅ Update magic word status to reflect payment success
                        db.collection("magicWordUser").document(magic_word_user_id).update({
                            "paymentStatus": "success",
                            "orderStatus": "booked",
                            "serviceOrderId": order_result.get("service_order_id"),
                            "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
                        })
                        
                        # Send confirmation message
                        msg_result = send_booking_confirmation_message(chat_id, booking_details)
                        print(f"📨 Confirmation message sent: {msg_result}")
                    else:
                        logging.warning(f"⚠️ Booking order creation failed: {order_result.get('error')}")
                else:
                    print(f"⏳ Payment pending/failed - Order not created yet")
                    # Send service request confirmation (not booking confirmation)
                    msg_result = send_service_request_message(chat_id, magic_word, booking_details)
                    print(f"📨 Service request message sent: {msg_result}")
            else:
                logging.warning(f"⚠️ Service request creation failed: {sr_result.get('error')}")
        
        # 🎫 Create booking order when status changes to completed (if not already created via payment)
        if new_status == "completed" and service_request_id:
            print(f"🎫 Creating booking order from completed status...")
            order_result = create_service_order(
                magic_word_user_id, 
                service_request_id,
                booking_details
            )
            print(f"🎫 Order result: {order_result}")
            
            if order_result.get("success"):
                msg_result = send_booking_confirmation_message(chat_id, booking_details)
                print(f"📨 Confirmation message sent: {msg_result}")
            else:
                logging.warning(f"⚠️ Booking order creation failed: {order_result.get('error')}")
        
        return jsonify({
            "success": True,
            "new_status": new_status,
            "payment_status": payment_status,
            "message": f"Status updated to {new_status} with payment status: {payment_status}"
        })
        
    except Exception as e:
        logging.exception("Error updating magic word status")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/magic-words/<magic_word_user_id>/send-message", methods=["POST"])
def send_message_to_user(magic_word_user_id):
    """
    ✅ Send a message to the user's chat
    """
    try:
        from datetime import datetime
        
        # ✅ Get JSON body
        request_body = request.get_json()
        
        if not request_body:
            print("❌ No JSON body received")
            return jsonify({"success": False, "error": "Request body is empty"}), 400
        
        message_type = request_body.get("messageType")
        message_content = request_body.get("message", "")
        chat_id = request_body.get("chatId")
        
        print(f"📨 MESSAGE DETAILS:")
        print(f"   Message Type: {message_type}")
        print(f"   Chat ID: {chat_id}")
        print(f"   Content Length: {len(message_content) if message_content else 0}")
        
        if not chat_id:
            return jsonify({"success": False, "error": "Chat ID is required"}), 400
        
        if not message_type or not message_content:
            return jsonify({"success": False, "error": "Message type and content are required"}), 400
        
        # ✅ Send message based on type
        db = get_project_b_firestore()
        
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500
        
        try:
            chat_doc = db.collection("chats").document(chat_id).get()
            if not chat_doc.exists:
                print(f"⚠️ Chat {chat_id} not found")
                return jsonify({"success": False, "error": "Chat not found"}), 404
            
            chat_location = chat_doc.to_dict().get("location") if chat_doc.exists else None
            
            message_data = {
                "role": "assistant",
                "content": message_content,
                "user_id": "SystemG",
                "created_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "location": chat_location,
            }
            
            # Add message to chat
            db.collection("chats").document(chat_id).collection("messages").add(message_data)
            
            logging.info(f"✅ Message sent to chat {chat_id}")
            print(f"✅ Message sent successfully to chat {chat_id}")
            print(f"   Type: {message_type}")
            print(f"   Preview: {message_content[:50]}...")
            
            return jsonify({
                "success": True,
                "message": "Message sent successfully",
                "messageType": message_type,
                "chatId": chat_id
            }), 200
        
        except Exception as e:
            logging.exception(f"Error sending message to chat: {e}")
            print(f"❌ Chat operation error: {str(e)}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    except Exception as e:
        logging.exception("Error in send_message_to_user endpoint")
        print(f"❌ Endpoint error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

# @app.route("/api/service-categories", methods=["GET"])
# def get_service_categories():
#     """Fetch all service categories from Firestore"""
#     try:
#         from firebase_setup import get_project_b_firestore
        
#         db = get_project_b_firestore()
        
#         # Fetch from serviceCategories collection
#         categories_ref = db.collection("serviceCategories").stream()
#         categories = []
        
#         for doc in categories_ref:
#             category_data = doc.to_dict()
#             categories.append({
#                 "id": doc.id,
#                 "title": category_data.get("title", ""),
#                 "name": category_data.get("name", ""),
#                 "description": category_data.get("description", "")
#             })
        
#         print(f"📋 Loaded {len(categories)} service categories")
#         return jsonify({
#             "success": True,
#             "categories": categories
#         })
    
#     except Exception as e:
#         logging.exception("Error fetching service categories")
#         return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/monuments", methods=["GET"])
def get_monuments():
    """Get all monuments"""
    try:
        db = get_project_b_firestore()
        monuments_ref = db.collection("serviceMonument")
        monuments = [{"id": doc.id, **doc.to_dict()} for doc in monuments_ref.stream()]
        
        return jsonify({
            "success": True,
            "monuments": monuments
        })
    except Exception as e:
        logging.exception("Error fetching monuments")
        return jsonify({"success": False, "error": str(e)}), 500


# ✅ ADD THIS NEW ENDPOINT
@app.route("/api/service-languages", methods=["GET"])
def get_service_languages():
    """✅ Get all languages from serviceLanguage collection"""
    try:
        db = get_project_b_firestore()
        
        # ✅ Fetch all documents from serviceLanguage collection
        languages_ref = db.collection("serviceLanguage").stream()
        
        languages = []
        for doc in languages_ref:
            lang_data = doc.to_dict()
            languages.append({
                "id": doc.id,
                "title": lang_data.get("title") or lang_data.get("name"),
                "name": lang_data.get("name"),
                "code": lang_data.get("code"),
                "created_at": lang_data.get("created_at"),
            })
        
        logging.info(f"✅ Loaded {len(languages)} languages")
        print(f"📚 Languages loaded: {[l['title'] for l in languages]}")
        
        return jsonify({
            "success": True,
            "languages": languages,
            "count": len(languages)
        }), 200

    except Exception as e:
        logging.exception(f"Error fetching service languages: {e}")
        print(f"❌ Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/monuments/<monument_id>/services", methods=["GET"])
def get_services_by_monument(monument_id):
    """Get services available for a specific monument - ONLY isAvailable=true"""
    try:
        db = get_project_b_firestore()
        
        print(f"🏛️ Fetching services for monument: {monument_id}")
        
        # Get the monument document
        monument_doc = db.collection("serviceMonument").document(monument_id).get()
        if not monument_doc.exists:
            print(f"⚠️ Monument {monument_id} not found")
            return jsonify({
                "success": False,
                "services": [],
                "error": f"Monument not found"
            }), 404
        
        monument_data = monument_doc.to_dict() or {}
        print(f"🏛️ Monument data keys:", list(monument_data.keys()))
        
        # ✅ Get serviceAvilable array from monument document
        service_available = monument_data.get("serviceAvilable", [])
        
        if not service_available:
            print(f"⚠️ No serviceAvilable array found in monument")
            return jsonify({
                "success": True,
                "services": [],
                "message": "No services available for this monument"
            })
        
        print(f"📦 Total services in serviceAvilable: {len(service_available)}")
        
        # ✅ Debug: Print all services and their isAvailable status
        for idx, service in enumerate(service_available):
            is_avail = service.get("isAvilable")
            print(f"   Service {idx}: title={service.get('title')}, isAvailable={is_avail}, type={type(is_avail)}, serviceId={service.get('id')} ")
        
        # ✅ Filter ONLY services where isAvailable is true
        available_services = []
        for service in service_available:
            is_available = service.get("isAvilable", False)
            # Only include if isAvailable is boolean True
            if is_available is True:
                available_services.append(service)
                print(f"   ✅ Including: {service.get('title')}")
            else:
                print(f"   ❌ Skipping: {service.get('title')} (isAvailable={is_available})")
        
        print(f"✅ Found {len(available_services)} AVAILABLE services out of {len(service_available)} total")
        
        if not available_services:
            print(f"⚠️ NO services have isAvailable=true")
            return jsonify({
                "success": True,
                "services": [],
                "message": "No available services for this monument"
            })
        
        # ✅ Format services for dropdown - ONLY available ones
        formatted_services = [
            {
                "id": service.get("id", ""),
                "title": service.get("title", ""),
                "name": service.get("name", ""),
                "description": service.get("description", ""),
                "isAvilable": True  # ✅ Confirmed these are all true
            }
            for service in available_services
        ]
        
        print(f"✅ Returning {len(formatted_services)} formatted services:")
        for svc in formatted_services:
            print(f"   - {svc['title']}")
        
        return jsonify({
            "success": True,
            "services": formatted_services
        })
        
    except Exception as e:
        logging.exception(f"Error fetching services for monument {monument_id}")
        print(f"❌ Error: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "services": []
        }), 500

@app.route("/api/chats/<chat_id>/toggle-interaction", methods=["PUT"])
def toggle_human_interaction(chat_id):
    """
    ✅ Toggle isHumanInteraction field in chats collection
    - true = kabirTeam (Human Support)
    - false = kabirAI (AI Assistant)
    """
    try:
        request_body = request.get_json() or {}
        is_human_interaction = request_body.get("isHumanInteraction", False)
        
        print(f"🔄 TOGGLE HUMAN INTERACTION")
        print(f"   Chat ID: {chat_id}")
        print(f"   Is Human Interaction: {is_human_interaction}")
        print(f"   Mode: {'kabirTeam' if is_human_interaction else 'kabirAI'}")
        
        db = get_project_b_firestore()
        
        if db is None:
            return jsonify({"success": False, "error": "Firestore not initialized"}), 500
        
        try:
            # ✅ Check if chat exists
            chat_doc = db.collection("chats").document(chat_id).get()
            if not chat_doc.exists:
                return jsonify({"success": False, "error": "Chat not found"}), 404
            
            # ✅ Update isHumanInteraction field
            db.collection("chats").document(chat_id).update({
                "isHumanInteraction": is_human_interaction,
                "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
            })
            
            logging.info(f"✅ Chat {chat_id} updated: isHumanInteraction = {is_human_interaction}")
            print(f"✅ Successfully updated chat {chat_id}")
            
            return jsonify({
                "success": True,
                "message": f"Switched to {'kabirTeam' if is_human_interaction else 'kabirAI'}",
                "isHumanInteraction": is_human_interaction,
                "mode": "kabirTeam" if is_human_interaction else "kabirAI"
            }), 200
        
        except Exception as e:
            logging.exception(f"Error updating chat: {e}")
            print(f"❌ Chat update error: {str(e)}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    except Exception as e:
        logging.exception("Error in toggle_human_interaction endpoint")
        print(f"❌ Endpoint error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# Add this route to your Flask app

@app.route('/api/magic-words/user/<user_id>', methods=['GET'])
def get_user_magic_words(user_id):
    """Fetch all magic word requests for a specific user from magicWordUser collection"""
    try:
        from customerService.user_summary import _ts_to_iso, _iso_to_readable
        
        print(f"📋 Fetching magic words for user: {user_id}")
        
        # Query magicWordUser collection where userId matches
        db = get_project_b_firestore()
        
        if db is None:
            return jsonify({
                'found': False,
                'error': 'Firestore not initialized',
                'requests': []
            }), 500
        
        requests_ref = db.collection('magicWordUser').where('userId', '==', user_id)
        docs = requests_ref.stream()
        
        requests_list = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            
            # Convert timestamp to readable format
            if 'matchedAt' in data:
                try:
                    iso = _ts_to_iso(data['matchedAt'])
                    data['matchedAt_readable'] = _iso_to_readable(iso)
                except:
                    data['matchedAt_readable'] = str(data.get('matchedAt', 'N/A'))
            
            if 'createdAt' in data:
                try:
                    iso = _ts_to_iso(data['createdAt'])
                    data['createdAt_readable'] = _iso_to_readable(iso)
                except:
                    data['createdAt_readable'] = str(data.get('createdAt', 'N/A'))
            
            requests_list.append(data)
        
        if not requests_list:
            print(f"⚠️ No requests found for user {user_id}")
            return jsonify({
                'found': False,
                'requests': [],
                'count': 0
            }), 200
        
        # Sort by matchedAt descending (newest first)
        requests_list.sort(
            key=lambda x: x.get('matchedAt') or x.get('createdAt', ''), 
            reverse=True
        )
        
        print(f"✅ Found {len(requests_list)} requests for user {user_id}")
        for idx, req in enumerate(requests_list, 1):
            print(f"   {idx}. Magic Word: {req.get('magicWord')}, Status: {req.get('status')}")
        
        return jsonify({
            'found': True,
            'requests': requests_list,
            'count': len(requests_list)
        }), 200
        
    except Exception as e:
        logging.exception(f"Error fetching user magic words: {str(e)}")
        print(f"❌ Error fetching user magic words: {str(e)}")
        return jsonify({
            'found': False,
            'error': str(e),
            'requests': [],
            'count': 0
        }), 500

if __name__ == "__main__":
    app.run(debug=True)
