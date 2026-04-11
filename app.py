
import http.server
import socketserver
import json
import sqlite3
import urllib.request
from urllib.parse import urlparse, parse_qs
import os
from datetime import datetime

# CONFIG
API_TOKEN = "Z6G7CVQYVOICREKFSBM3ZLYQRDYFKOWI5JIBG9PRH20X4WF4E1MTVUU2WPNT8D3A"
BANK_ACC = "9939899899999"
BANK_CODE = "MB"
PORT = 8000

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        clean_path = parsed_path.path.rstrip('/')
        
        if clean_path == '':
            self.path = '/index.html'
        elif clean_path == '/admin':
            self.path = '/admin.html'
        
        # API GET Endpoints
        if clean_path == '/api/admin/products':
            return self.send_json(self.get_all('products'))
        elif clean_path == '/api/admin/customers':
            return self.send_json(self.get_all('customers'))
        elif clean_path == '/api/admin/orders':
            return self.send_json(self.get_orders_with_details())
            
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode('utf-8'))

        if self.path == '/api/create-order':
            self.send_json(self.create_order(data))
        elif self.path == '/api/check-payment':
            self.send_json(self.check_payment(data))
        elif self.path == '/api/admin/products':
            self.send_json(self.save_product(data))
        elif self.path == '/api/admin/orders':
            self.send_json(self.admin_create_order(data))
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path.startswith('/api/admin/'):
            table = parsed_path.path.split('/')[-1]
            query = parse_qs(parsed_path.query)
            item_id = query.get('id', [None])[0]
            if item_id:
                self.send_json(self.delete_item(table, item_id))
            else:
                self.send_error(400, "Missing ID")

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def get_all(self, table):
        try:
            conn = sqlite3.connect('brain.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table}")
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            return {"error": str(e)}

    def get_orders_with_details(self):
        try:
            conn = sqlite3.connect('brain.db')
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT orders.*, customers.name as customer_name, customers.phone as customer_phone, products.name as product_name 
                FROM orders 
                JOIN customers ON orders.customer_id = customers.id
                JOIN products ON orders.product_id = products.id
                ORDER BY orders.id DESC
            ''')
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            return {"error": str(e)}

    def save_product(self, data):
        try:
            conn = sqlite3.connect('brain.db')
            cursor = conn.cursor()
            if data.get('id'):
                cursor.execute("UPDATE products SET name=?, price=?, quantity=?, description=? WHERE id=?",
                               (data['name'], data['price'], data['quantity'], data['description'], data['id']))
            else:
                cursor.execute("INSERT INTO products (name, price, quantity, description) VALUES (?, ?, ?, ?)",
                               (data['name'], data['price'], data['quantity'], data['description']))
            conn.commit()
            conn.close()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_item(self, table, item_id):
        try:
            conn = sqlite3.connect('brain.db')
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            conn.commit()
            conn.close()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_order(self, data):
        try:
            conn = sqlite3.connect('brain.db')
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM customers WHERE phone = ?", (data['phone'],))
            row = cursor.fetchone()
            if row:
                customer_id = row[0]
            else:
                cursor.execute("INSERT INTO customers (name, phone, registration_date) VALUES (?, ?, ?)",
                               (data['name'], data['phone'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                customer_id = cursor.lastrowid
            
            quantity = data.get('quantity', 1)
            address = data.get('address', '')
            note = data.get('note', '')
            
            cursor.execute("INSERT INTO orders (customer_id, product_id, amount, status, purchase_date, quantity, address, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (customer_id, data['product_id'], data['amount'], 'pending', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), quantity, address, note))
            order_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            description = f"DH{order_id}"
            qr_url = f"https://qr.sepay.vn/img?acc={BANK_ACC}&bank={BANK_CODE}&amount={data['amount']}&des={description}&template=compact"
            return {"success": True, "order_id": order_id, "qr_url": qr_url, "description": description}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def admin_create_order(self, data):
        res = self.create_order(data)
        if res.get('success'):
            self.update_order_status(res['order_id'], 'success')
        return res

    def check_payment(self, data):
        order_id = data.get('order_id')
        description = f"DH{order_id}"
        url = "https://my.sepay.vn/userapi/transactions/list"
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Bearer {API_TOKEN}')
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                transactions = result.get('transactions', [])
                for t in transactions:
                    content = t.get('transaction_content', '')
                    if description.upper() in content.upper():
                        self.update_order_status(order_id, 'success')
                        return {"success": True, "status": "paid"}
                return {"success": True, "status": "pending"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_order_status(self, order_id, status):
        try:
            conn = sqlite3.connect('brain.db')
            cursor = conn.cursor()
            cursor.execute("SELECT status, product_id, quantity FROM orders WHERE id = ?", (order_id,))
            row = cursor.fetchone()
            if row and row[0] != 'success' and status == 'success':
                qty_to_reduce = row[2] if row[2] else 1
                cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
                cursor.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?", (qty_to_reduce, row[1]))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error updating order: {e}")

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), MyHandler) as httpd:
        print(f"Serving at port {PORT}")
        httpd.serve_forever()
