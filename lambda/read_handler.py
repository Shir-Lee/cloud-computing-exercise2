import json
import os
import redis
import pymysql
from datetime import datetime

group_members_table = 'group_members_table'
group_messages_table = 'group_messages_table'
user_messages_table = 'user_messages_table'
ttl_seconds = 86400  # Key will expire in a day


def read_messages_lambda(event, context):
    global result

    try:
        # parse input
        user_id = event['queryStringParameters']['user_id']
        min_timestamp = event['queryStringParameters']['min_timestamp']  # '2024-07-01 09:00:00.0'

        # cache
        redis_host = os.environ['REDIS_HOST']
        client = redis.Redis(host=redis_host, port=6379, db=0)
        # records = client.get(user_id)
        cache_messages = client.lrange(user_id, 0, -1)
        # ttl
        client.expire(user_id, ttl_seconds)
        # check messages in cache
        if cache_messages:
            min_timestamp_datetime = datetime.strptime(min_timestamp, '%Y-%m-%d %H:%M:%S.%f')
            oldest_message = cache_messages[-1]
            oldest_message_timestamp = datetime.strptime(oldest_message.decode('utf-8').split('::')[0], '%Y-%m-%d %H:%M:%S.%f')
            # print(str(oldest_message_timestamp))
            if oldest_message_timestamp <= min_timestamp_datetime:
                records = []
                for message in cache_messages:
                    message_timestamp = datetime.strptime(message.decode('utf-8').split('::')[0], '%Y-%m-%d %H:%M:%S.%f')
                    if message_timestamp >= min_timestamp_datetime:
                        records.append(message)
                    else:
                        break
                return {
                    'statusCode': 200,
                    'body': json.dumps(f'success in reading messages via cache: {records}')
                }

        # if the timestamp not in cache (eirther empty cache or doesn't include all required messages)
        # then read from the db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("USE mydatabase")
                # messages (from users and groups)
                cursor.execute(f"""
                SELECT timestamp, 0 as is_group, sending_user_id, message_text FROM {user_messages_table} 
                WHERE receiving_user_id='{user_id}'
                AND timestamp >= '{min_timestamp}'
                UNION
                SELECT timestamp, 1 as is_group, sending_user_id, message_text FROM {group_messages_table} 
                JOIN {group_members_table} ON {group_messages_table}.group_id={group_members_table}.group_id
                WHERE {group_members_table}.user_id='{user_id}'
                AND timestamp >= '{min_timestamp}'
                """)
                records = cursor.fetchall()

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps(f'success in reading messages via db: {str(records)}')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in reading messages: {e}")
        }
        return result
