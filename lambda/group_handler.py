import json
import uuid
from datetime import datetime
import pymysql
import os
import redis

users_table = 'users_table'
groups_table = 'groups_table'
group_members_table = 'group_members_table'
group_messages_table = 'group_messages_table'
cache_length = 20


def create_group_lambda(event, context):
    global result

    try:
        # parse input
        group_name = event['queryStringParameters']['group_name']

        # update db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                # create table
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS mydatabase;')
                cursor.execute("USE mydatabase")
                cursor.execute(
                    f'CREATE TABLE IF NOT EXISTS {groups_table} (group_id VARCHAR(255) PRIMARY KEY, group_name VARCHAR(255));')
                # check if group exists: no need, since the group-name is not unique here, just the group-id
                # generate id
                group_id = str(uuid.uuid4())
                # record in table
                cursor.execute(f"INSERT INTO {groups_table} (group_id, group_name) VALUES ('{group_id}', '{group_name}');")
            connection.commit()

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps(f'success in creating group! group_id: {group_id}')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in creating group: {e}")
        }
        return result


def update_group_lambda(event, context):
    global result

    try:
        # parse input
        user_id = event['queryStringParameters']['user_id']
        group_id = event['queryStringParameters']['group_id']
        to_be_added = bool(int(event['queryStringParameters']['to_be_added']))  # add/remove

        # update db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                # create table
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS mydatabase;')
                cursor.execute("USE mydatabase")
                cursor.execute(
                    f'CREATE TABLE IF NOT EXISTS {group_members_table} (group_id VARCHAR(255), user_id VARCHAR(255), PRIMARY KEY (group_id, user_id));')
                # record in table
                if to_be_added:
                    cursor.execute(
                        f"INSERT INTO {group_members_table} (group_id, user_id) VALUES ('{group_id}', '{user_id}');")
                    action = 'user has been added'
                else:
                    cursor.execute(
                        f"DELETE FROM {group_members_table} WHERE group_id='{group_id}' AND user_id='{user_id}';")
                    action = 'user has been removed'
            connection.commit()

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps(f'success in updating group: {action}')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in updating group: {e}")
        }
        return result


def send_group_lambda(event, context):
    global result

    try:
        # parse input
        sending_user_id = event['queryStringParameters']['sending_user_id']
        group_id = event['queryStringParameters']['group_id']
        message_text = event['queryStringParameters']['message_text']

        # update db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                # create table
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS mydatabase;')
                cursor.execute("USE mydatabase")
                cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {group_messages_table} (
                message_id VARCHAR(255) PRIMARY KEY,
                sending_user_id VARCHAR(255),
                group_id VARCHAR(255),
                message_text VARCHAR(255),
                timestamp TIMESTAMP
                );
                """)

                # message details
                message_id = str(uuid.uuid4())
                message_timestamp = datetime.now()

                # record
                cursor.execute(f"""
                INSERT INTO {group_messages_table} 
                (message_id, sending_user_id, group_id, message_text, timestamp) VALUES 
                ('{message_id}', '{sending_user_id}', '{group_id}', 
                '{message_text}', '{str(message_timestamp)}');
                """)

                # get users in the group
                cursor.execute(f"""SELECT user_id FROM {group_members_table} WHERE group_id='{group_id}';""")
                records = cursor.fetchall()

            connection.commit()

        # send to cache
        redis_host = os.environ['REDIS_HOST']
        cache_client = redis.Redis(host=redis_host, port=6379, db=0)
        is_group = 1
        value = f'{str(message_timestamp)}:: {is_group} {sending_user_id}:: {message_text}'
        # cache_client.set(receiving_user_id, value)
        # cache_client.delete(receiving_user_id)
        for row in records:
            receiving_user_id = row[0]
            if receiving_user_id != sending_user_id:
                # push the new message
                cache_client.lpush(receiving_user_id, value)
                # remove the oldest message
                if cache_client.llen(receiving_user_id) > cache_length:
                    cache_client.rpop(receiving_user_id)

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps('success in sending to group')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in sending to group: {e}")
        }
        return result
