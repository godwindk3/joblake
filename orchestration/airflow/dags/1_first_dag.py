from airflow.sdk import dag, task

@dag(
    dag_id="first_dag",
)
def first_dag():

    @task.python
    def first_task():
        print("This is the first task")

    @task.python
    def second_task():
        print("This is the second task AASD SAD")

    @task.python
    def third_task():
        print("This is the third task asd asd asd asd")

    @task.python
    def version_task():
        print("new version")

    first = first_task()
    second = second_task()
    third = third_task()
    version = version_task()

    first >> second >> third >> version 

# register
first_dag()
