import boto3
import csv
import json
import time
from datetime import datetime

def datetime_converter(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Type {type(o)} not serializable")

def lambda_handler(event, context):
    # Initialize EC2, SSM, and S3 clients
    ec2_client = boto3.client('ec2')
    ssm_client = boto3.client('ssm')
    s3_client = boto3.client('s3')

    # Define your S3 bucket name and desired object key
    s3_bucket_name = "your-s3-bucket-name"  # Replace with your S3 bucket name
    s3_object_key = "instance_outputs.csv"    # The name you want for the CSV in S3

    # Get a list of all instances
    response = ec2_client.describe_instances()
    
    linux_instances = []

    # Categorize instances as Linux based on platform and state
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            state = instance['State']['Name']
            platform = instance.get('Platform', 'Linux')  # Default to Linux if not specified
            
            if state == 'running' and platform != 'windows':
                linux_instances.append(instance_id)

    # Send a command to all Linux instances and get CommandId
    if linux_instances:
        try:
            command_response = ssm_client.send_command(
                DocumentName="AWS-RunShellScript",
                InstanceIds=linux_instances,
                Parameters={"commands": ["echo Hello World"]}
            )
            command_id = command_response['Command']['CommandId']

            # Open CSV file for writing outputs
            csv_file_path = "/tmp/instance_outputs.csv"
            with open(csv_file_path, mode='w', newline='') as csvfile:
                fieldnames = ['InstanceId', 'Status', 'OutputPayload']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                # Poll for command invocation results for each instance
                for instance_id in linux_instances:
                    while True:
                        try:
                            command_invocation = ssm_client.get_command_invocation(
                                CommandId=command_id,
                                InstanceId=instance_id
                            )
                            # Check if the command invocation is completed
                            if command_invocation['Status'] in ['Success', 'Failed', 'Cancelled']:
                                # Write the instance details to CSV
                                writer.writerow({
                                    'InstanceId': instance_id,
                                    'Status': command_invocation['Status'],
                                    'OutputPayload': command_invocation.get('StandardOutputContent', 'N/A')
                                })
                                break
                        except ssm_client.exceptions.InvocationDoesNotExist:
                            time.sleep(5)  # Wait before retrying

            # Upload CSV file to S3
            with open(csv_file_path, 'rb') as data:
                s3_client.put_object(Bucket=s3_bucket_name, Key=s3_object_key, Body=data)

            # Return success message
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'CSV file created and uploaded to S3 successfully.',
                    'S3Bucket': s3_bucket_name,
                    'S3ObjectKey': s3_object_key
                }, default=datetime_converter)
            }

        except Exception as e:
            print(f"Error during SSM command execution or S3 upload: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({"error": str(e)})
            }
    else:
        return {
            'statusCode': 200,
            'body': json.dumps({"message": "No running Linux instances found."})
        }
