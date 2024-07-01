# Cloud Computing Exercise 2

A cloud-based messaging system (backend side), which is serverless.  
The system includes the following actions, each has its own endpoint:
1. Register a new user (generating a new id). It returns the user id.
-	Example: POST/register?user_name=shir
2. Block a user from sending a message (note that ‘to_block=1’ apply blocking, and ‘to_block=0’ remove blocking).
-	Example: POST/ block?blocking_user_id=3&blocked_user_id=1&to_block=1
3. Send a message from a user to another user (via its id), unless blocking is applied.
-	Example: POST/ send?sending_user_id=1&receiving_user_id=3&message_text=hi
4.	Creating a group. It returns the group id.
-	Example: POST/create_group?group_name=bambis
5.	Adding / removing users (note that ‘to_be_added=1’ adds the user to the group, while ‘to_be_added=0’ removes from the group).
Groups have no admin and users can add/remove themselves from the group using the group’s id (as in telegram). Also there can be multiple groups with same name (group id is unique).
-	Example: POST/ update_group?user_id=1&group_id=2e86f3d2-9705-4acb-b1c7-980e5bb05ada&to_be_added=1
6. Sending messages to a group.
-	Example: POST/send_group?sending_user_id=1&group_id=2e86f3d2-9705-4acb-b1c7-980e5bb05ada&message_text=hello_group
7. Users can check for their messages (assuming users check at least once a minute).
Example: POST/read_messages?user_id=2&min_timestamp=2024-07-01 09:10:00.0

## Getting Started

### Prerequisites

You need to use AWS account and Pulumi account.
- [https://aws.amazon.com]
- [https://www.pulumi.com]

### Installing 

After configuring Pulumi and AWS and installing their CLI, do the following instructions:
- Clone the project locally
- Open commandline to the project's directory
- Pass the user-name and password of the DB via pulumi-config. For instance:
pulumi config set db_user shir          
pulumi config set db_password YourPassword
- Run: 
    pulumi up

Pulumi will deploy the system and its requirements. At the end you will receive all endpoints (for each of the actions mentioned above).

In order to delete the system, run:
    pulumi destroy

## Data

### Database (mysql aurora)

The choice of Relational-DB was due to the need of querying that non-relational-DB would need to scan (requires more time and cost) and we wanted to avoid it. The choice of Aurora allows simple management, redundancy and scaling. Aurora is fault tolerant by design (allowing to tolerate a failure of an AZ without loss of data). The cluster volume spans multiple AZ in a single Region, and each AZ contains a copy of the data. 

The database consists of the following tables:
•	Users table: 
-	Columns: user_id, user_name
•	Blocks table: 
-	Columns: blocking_blocked_pair (pair of the two user ids)
•	User messages table (for messages between two users): 
-	Columns: message_id, sending_user_id, receiving_user_id, message_text, timestamp (of sending the message)
•	Groups table: 
-	Columns: group_id, group_name
•	Group members table:
-	Columns: group_id, user_id
•	Group messages table (for messages within a group):
-	Columns: message_id, sending_user_id, group_id, message_text, timestamp (of sending the message)

Note: In general, the DB tables should include indexes and relations between the different id-fields, for the purpose of speed. However, due to an issue with creating the DB via pulumi “main”, the DB is created within the lambda without refering to indexing and relations.

### Cache (redis)

The use of caching is required to allow fast response while checking messages with high frequency (reading the messages at least once a minute). 
Redis suits the case of caching for low-latency, in-memory data access. Redis was chosen since it allows complex data-structures (such as list which was used here for the ordered messages). We use ElasticCache which allows simple management, availability and scaling.
The caching structure:
•	Key: user id (which receives the message)
•	Value: list of messages of size k (the last k messages sent to that user, ordered by the time of sending)
Note that a key of the conversation (e.g. ordered pair of user_id-user_id or group_id) might be more efficient since we can save less keys. However, it is more complex to extract the keys that are relevant to the user who checks the messages.

### Flow

The caching allows speed but with limited memory. Hence it holds both TTL for the keys and limited size k of the list (the value).
Each time a user sends a message (either to another user or to a group), the message is saved both in the DB and in the cache (if the list in that key exceeds the allowed size, the we removed the oldest message in the list).
When a user reads the messages, the system first checks the cache. If the cache is empty (for any reason) or doesn’t include all required messages (since the size of the list is limited), then it queries the DB (for the user-id and minimal-timestamp given).

Note: Data sanitization was not applied here since it is not the focus of the assignment, but should be included in general to avoid security issues. 
Same for handling cases (such as assuring a user exists before blocking etc.) which were not applied should be included in general.

### Client side
The client side (which is not implemented here) is responsible on storing all messages that are on the device. It calls to check the new messages that accumulated each time (in the call it sends the timestamp from which the messages that were sent afterwards will return). The client side also organize the messages for the UI (e.g. by conversations).

## Scalability
This system requires relatively high frequency of requests (users will check messages at least once a minute) and low latency for normal operation. In messaging application use case users can send to each other a high volume of messages, and expect quick response.

It means that querying the database each time would be too slow and runtime. Therefore, an active on-write caching was used (as mentioned earlier), such that when a message is sent the lambda writes also to the cache, and when messages are checked the lambda first check the cache and only if needed (if not all messages are in the cache) – then it queries the DB. This is due to the assumption that in this use case of messaging system most of the messages are sent and read instantly – hence it is likely to hit the cache. 

Scalability affects the system in both load and in cost. The more users (and messages volume) require larger DB storage, larger cache storage and the ability to handle more requests. 
The system is fully built on scalable components:
-	Serverless computing – which allows to expand the number of lambdas (up to 1k in parallel). 
-	Aurora DB – which can scale up easily (in general we did not apply clean-up of old data or moving to an archive, but will be required in a high scale system).
-	Redis cache – which allows fast call to the last messages sent which are more probable to be read close to the time it was sent, and therefore less calls to the DB.

Each lambda runs in ~X milliseconds (which is 0.001X seconds), and can run up to 1000 times in parallel. Hence, the number of requests that can be handles in a second: (1000/X)*1000=1M/X.
The mean runtime for each of the lambdas (in ms):
1.	Register: 42
2.	Block: 35
3.	Send a message to a user: 66
4.	Create a group: 52
5.	Adding / removing user from a group: 35
6.	Send a message to a group: 52
7.	Read messages: 10 for cache, 20 for DB

The range is 35-66ms. Specifically, the response time for reading the messages when going to DB is twice then when the cache is hit. In the worse-case X=66 which is ~15K responses per second. However, reading messages from cache have X=10 which is 100K responses per second, and under the assumption such call is a substantial volume of the calls in massaging system.

Assuming that 1000s users have 1million requests a day (24 hours), then it requires ~12 requests a second (1M/24/3600=11.6). Meaning that 10,000s of users requires about 120 requests a second, and millions of users requires about 12K. Hence the system can handle all of these cases, and scaling to millions of users.
