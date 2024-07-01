import pulumi
import pulumi_aws as aws
import json
import pulumi_aws_apigateway as apigateway

config = pulumi.Config()
db_user = config.require("db_user")
db_password = config.require_secret("db_password")
cache_port = 6379
db_port = 3306


def create_role():
    # execution role to use for the lambda function
    assume_role_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com", },
        }],
    })

    policy_db = aws.iam.Policy("policy_db",
                               policy=json.dumps({
                                   "Version": "2012-10-17",
                                   "Statement": [{
                                       "Action": [
                                           "dynamodb:DeleteItem",
                                           "dynamodb:GetItem",
                                           "dynamodb:PutItem",
                                           "dynamodb:Scan",
                                           "dynamodb:UpdateItem",
                                           "dynamodb:Query",
                                           "dynamodb:DescribeTable",
                                           "dynamodb:ListTables",
                                           "elasticache:*",
                                           "rds:*",
                                           "logs:*",
                                           "ec2:CreateNetworkInterface",
                                           "ec2:DescribeNetworkInterfaces",
                                           "ec2:DeleteNetworkInterface"
                                       ],
                                       "Effect": "Allow",
                                       "Resource": "*",
                                   }],
                               }))

    role = aws.iam.Role("role_exercise2",
                        assume_role_policy=assume_role_policy,
                        managed_policy_arns=[
                            aws.iam.ManagedPolicy.AWS_LAMBDA_BASIC_EXECUTION_ROLE,
                            policy_db.arn,
                        ])

    _ = aws.iam.RolePolicyAttachment(
        "lambdaRolePolicyAttachment",
        role=role.name,
        policy_arn="arn:aws:iam::aws:policy/AmazonElastiCacheFullAccess"
    )

    return role


def create_networking():
    # Create a VPC
    vpc = aws.ec2.Vpc(
        "vpc",
        cidr_block="10.0.0.0/16",
        enable_dns_support=True,
        enable_dns_hostnames=True
    )

    # Create subnet 1 in availability zone 1
    subnet_1 = aws.ec2.Subnet(
        "subnet1",
        vpc_id=vpc.id,
        cidr_block="10.0.1.0/24",
        availability_zone="eu-west-3a"
    )

    # Create subnet 2 in availability zone 2
    subnet_2 = aws.ec2.Subnet(
        "subnet2",
        vpc_id=vpc.id,
        cidr_block="10.0.2.0/24",
        availability_zone="eu-west-3b"
    )

    # Create subnet 2 in availability zone 2
    subnet_3 = aws.ec2.Subnet(
        "subnet3",
        vpc_id=vpc.id,
        cidr_block="10.0.3.0/24",
        availability_zone="eu-west-3c"
    )

    # Create an Internet Gateway
    _ = aws.ec2.InternetGateway(
        "aurora-redis-igw",
        vpc_id=vpc.id
    )

    subnets_ids = [subnet_1.id, subnet_2.id, subnet_3.id]

    return subnets_ids, vpc.id


def create_lambda_security(vpc_id, subnets_ids):
    # Allow outbound traffic on the default Redis port
    security_group = aws.ec2.SecurityGroup(
        "lambda-sg",
        description="Allow lambda access",
        vpc_id=vpc_id
    )

    egress_rule = aws.ec2.SecurityGroupRule(
        "lambda-sg-egress-db",
        type="egress",
        from_port=db_port,
        to_port=db_port,
        protocol="tcp",
        security_group_id=security_group.id,
        cidr_blocks=["0.0.0.0/0"],
    )

    egress_rule = aws.ec2.SecurityGroupRule(
        "lambda-sg-egress-cache",
        type="egress",
        from_port=cache_port,
        to_port=cache_port,
        protocol="tcp",
        security_group_id=security_group.id,
        cidr_blocks=["0.0.0.0/0"],
    )

    vpc_config = {
        "subnet_ids": subnets_ids,
        "security_group_ids": [security_group.id]
    }

    return vpc_config


def create_lambda(file_name, function_name, role, vpc_config, variables=None):
    # lambda function
    fn = aws.lambda_.Function(f"{function_name}_fn",
                              runtime="python3.12",
                              handler=f"{file_name}_handler.{function_name}_lambda",
                              role=role.arn,
                              code=pulumi.FileArchive("lambda.zip"),
                              vpc_config=vpc_config,
                              environment=aws.lambda_.FunctionEnvironmentArgs(variables=variables),
                              )

    api = apigateway.RestAPI(f"{function_name}_api",
                             routes=[
                                 apigateway.RouteArgs(path=f"/{function_name}", method=apigateway.Method.POST,
                                                      event_handler=fn)
                             ])

    pulumi.export(f"{function_name}_url:", api.url)


def create_cache(vpc_id, subnets_ids):
    # Create a security group for ElastiCache
    security_group = aws.ec2.SecurityGroup(
        "redis-sg",
        description="Allow Redis access",
        vpc_id=vpc_id,
        ingress=[  # Allow inbound traffic on the default Redis port
            aws.ec2.SecurityGroupIngressArgs(
                from_port=cache_port,
                to_port=cache_port,
                protocol="tcp",
                cidr_blocks=["0.0.0.0/0"],
            )
        ],
    )

    # Create a subnet group for ElastiCache
    subnet_group = aws.elasticache.SubnetGroup(
        "redis-subnet-group",
        subnet_ids=subnets_ids
    )

    # Create a Redis ElastiCache replication group with Multi-AZ enabled
    redis_replication_group = aws.elasticache.ReplicationGroup(
        "redis-replication-group",
        description="My Redis replication group",
        engine="redis",
        node_type="cache.t3.micro",
        num_cache_clusters=2,
        parameter_group_name="default.redis7",
        subnet_group_name=subnet_group.name,
        security_group_ids=[security_group.id],
        automatic_failover_enabled=True,
        multi_az_enabled=True
    )

    return redis_replication_group


def create_db(vpc_id, subnet_ids):
    # Allow outbound traffic on the default Redis port
    security_group = aws.ec2.SecurityGroup(
        "aurora-sg",
        vpc_id=vpc_id,
        description="Allow Aurora access",
        ingress=[
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp",
                from_port=db_port,
                to_port=db_port,
                cidr_blocks=["0.0.0.0/0"]
            )
        ]
    )

    # Create DB subnet group for Aurora
    aurora_subnet_group = aws.rds.SubnetGroup(
        "aurora-subnet-group",
        subnet_ids=subnet_ids,
        description="Subnet group for Aurora"
    )

    # Create Aurora cluster
    aurora_cluster = aws.rds.Cluster(
        "aurora-cluster",
        cluster_identifier="aurora-cluster",
        engine=aws.rds.EngineType.AURORA_MYSQL,
        master_username=db_user,
        master_password=db_password,
        db_subnet_group_name=aurora_subnet_group.name,
        vpc_security_group_ids=[security_group.id],
        skip_final_snapshot=True,
        availability_zones=["eu-west-3a", "eu-west-3b", "eu-west-3c"],
    )

    # Create Aurora cluster instance
    aurora_instance = aws.rds.ClusterInstance(
        "aurora-instance",
        cluster_identifier=aurora_cluster.id,
        instance_class="db.r5.large",
        engine="aurora-mysql",
        publicly_accessible=False
    )

    return aurora_cluster


lambda_role = create_role()
network_subnets_ids, network_vpc_id = create_networking()
redis = create_cache(network_vpc_id, network_subnets_ids)
aurora = create_db(network_vpc_id, network_subnets_ids)
lambda_vpc_config = create_lambda_security(network_vpc_id, network_subnets_ids)
env_variables = {"REDIS_HOST": redis.primary_endpoint_address,
                 "DB_HOST": aurora.endpoint,
                 "DB_USER": db_user,
                 "DB_PASS": db_password
                 }

create_lambda("user", "register", lambda_role, lambda_vpc_config, variables=env_variables)
# https://syobzgg5p3.execute-api.eu-west-3.amazonaws.com/stage/register?user_name=shir
create_lambda("user", "block", lambda_role, lambda_vpc_config, variables=env_variables)
# https://xpg36smji6.execute-api.eu-west-3.amazonaws.com/stage/block?blocking_user_id=7ad43600-fb44-4572-b0df-24dd2ffba3fe&blocked_user_id=3bf3d96c-2cc9-42b4-ab74-a05ba1d21b0d&to_block=1
create_lambda("user", "send", lambda_role, lambda_vpc_config, variables=env_variables)
# https://i1d1chc91e.execute-api.eu-west-3.amazonaws.com/stage/send?sending_user_id=3bf3d96c-2cc9-42b4-ab74-a05ba1d21b0d&receiving_user_id=7ad43600-fb44-4572-b0df-24dd2ffba3fe&message_text=hi

create_lambda("group", "create_group", lambda_role, lambda_vpc_config, variables=env_variables)
# https://462jh7fvn2.execute-api.eu-west-3.amazonaws.com/stage/create_group?group_name=bambis
create_lambda("group", "update_group", lambda_role, lambda_vpc_config, variables=env_variables)
# https://vc2jjop2c7.execute-api.eu-west-3.amazonaws.com/stage/update_group?user_id=3bf3d96c-2cc9-42b4-ab74-a05ba1d21b0d&group_id=8357cda7-6b68-4b66-b07b-60647eca717c&to_be_added=1
create_lambda("group", "send_group", lambda_role, lambda_vpc_config, variables=env_variables)
# https://x9g5o3hfqa.execute-api.eu-west-3.amazonaws.com/stage/send_group?sending_user_id=3bf3d96c-2cc9-42b4-ab74-a05ba1d21b0d&group_id=8357cda7-6b68-4b66-b07b-60647eca717c&message_text=hello_group

create_lambda("read", "read_messages", lambda_role, lambda_vpc_config, variables=env_variables)
# https://prefcdtqm0.execute-api.eu-west-3.amazonaws.com/stage/read_messages?user_id=7ad43600-fb44-4572-b0df-24dd2ffba3fe&min_timestamp=2024-07-01 15:31:00.0

