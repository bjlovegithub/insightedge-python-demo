from pyspark import Row
from pyspark import SparkContext
from pyspark.mllib.tree import DecisionTreeModel
from pyspark.sql import SQLContext
from pyspark.streaming import StreamingContext
from pyspark.streaming.kafka import KafkaUtils

from util.commons import DF_SUFFIX, IE_FORMAT, Utils

'''
bin/zookeeper-server-start.sh config/zookeeper.properties
bin/kafka-server-start.sh config/server.properties
bin/kafka-topics.sh --create --zookeeper localhost:2181 --replication-factor 1 --partitions 1 --topic test

Run simple kafka file producer from terminal
awk '{ print $0; system("sleep 0.1");}'  /code/insightedge-pyhton-demo/data/testData2/part-00000 | bin/kafka-console-producer.sh --broker-list localhost:9092 --topic test
cat  /code/insightedge-pyhton-demo/data/testData3/part-00000 | bin/kafka-console-producer.sh --broker-list localhost:9092 --topic test
awk '{ print $0; system("sleep 1");}'  /code/insightedge-pyhton-demo/data/rita2014jan.csv | bin/kafka-console-producer.sh --broker-list localhost:9092 --topic test

Show correct-incorrect ration in Zeppelin

%pyspark
gridDf = sqlContext.read.format("org.apache.spark.sql.insightedge").option("collection", "org.insightedge.pythondemo.FlightWithPrediction").load()
gridDf.registerTempTable("FlightWithPrediction")

%sql
select count(*)
from FlightWithPrediction
where prediction = actual

%sql
select count(*)
from FlightWithPrediction
where prediction <> actual

%sql
select
    (case when prediction = actual then 'Correct' ELSE 'Incorrect' END) as predicted,
    count(prediction) as count
from FlightWithPrediction
group by prediction, actual

%sql
select day_of_month as day, origin, destination, distance, carrier,
departure_delay_minutes as actual_delay_minutes,
(case when prediction = actual then 'Correct' ELSE 'Incorrect' END) as prediction
FROM FlightWithPrediction

'''


def load_mapping(mapping_name, sqlc):
    df = sqlc.read.format(IE_FORMAT).option("collection", mapping_name).load()
    return dict(df.map(lambda row: (row.key, row.integer_value)).collect())


def predict_and_save(rdd):
    if not rdd.isEmpty():
        parsed_flights = rdd.map(Utils.parse_flight)
        labeled_points = parsed_flights.map(lambda flight: Utils.create_labeled_point(flight, carrier_mapping, origin_mapping, destination_mapping))

        predictions = model.predict(labeled_points.map(lambda x: x.features))
        labels_and_predictions = labeled_points.map(lambda lp: lp.label).zip(predictions).zip(parsed_flights).map(to_row())

        df = sqlc.createDataFrame(labels_and_predictions)
        df.write.format(IE_FORMAT).mode("append").save(DF_SUFFIX + ".FlightWithPrediction")


def to_row():
    return lambda t: Row(actual=t[0][0],
                         prediction=t[0][1],
                         day_of_month=t[1].day_of_month,
                         day_of_week=t[1].day_of_week,
                         carrier=t[1].carrier,
                         tail_number=t[1].tail_number,
                         flight_number=t[1].flight_number,
                         origin_id=t[1].origin_id, origin=t[1].origin,
                         destination_id=t[1].destination_id,
                         destination=t[1].destination,
                         scheduled_departure_time=t[1].scheduled_departure_time,
                         actual_departure_time=t[1].actual_departure_time,
                         departure_delay_minutes=t[1].departure_delay_minutes,
                         scheduled_arrival_time=t[1].scheduled_arrival_time,
                         actual_arrival_time=t[1].actual_arrival_time,
                         arrival_delay_minutes=t[1].arrival_delay_minutes,
                         crs_elapsed_flight_minutes=t[1].crs_elapsed_flight_minutes,
                         distance=t[1].distance)


if __name__ == "__main__":
    sc = SparkContext(appName="Flight delay prediction job")
    ssc = StreamingContext(sc, 3)
    sqlc = SQLContext(sc)

    zkQuorum = "localhost:2181"
    topic = "python-blog"

    model = DecisionTreeModel(Utils.load_model_from_grid(sc))

    carrier_mapping = load_mapping(DF_SUFFIX + ".CarrierMap", sqlc)
    origin_mapping = load_mapping(DF_SUFFIX + ".OriginMap", sqlc)
    destination_mapping = load_mapping(DF_SUFFIX + ".DestinationMap", sqlc)

    kvs = KafkaUtils.createStream(ssc, zkQuorum, "spark-streaming-consumer", {topic: 1})
    lines = kvs.map(lambda x: x[1])
    lines.foreachRDD(lambda rdd: predict_and_save(rdd))

    ssc.start()
    ssc.awaitTermination()
