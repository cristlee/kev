import boto3
import json
import redis

from kev.exceptions import DocSaveError
from kev.backends.redis.db import RedisDB

class S3DB(RedisDB):

    conn_class = boto3.resource
    cache_class = redis.StrictRedis
    backend_id = 's3'

    def __init__(self,**kwargs):
        if kwargs.has_key('aws_secret_access_key') and kwargs.has_key('aws_access_key_id'):
            boto3.Session(aws_secret_access_key=kwargs['aws_secret_access_key'],
                aws_access_key_id=kwargs['aws_access_key_id'])
        self._s3 = boto3.resource('s3')
        self.bucket = kwargs['bucket']
        self._redis = self.cache_class(kwargs['redis_host'],port=kwargs['redis_port'])

    #CRUD Operation Methods

    def save(self,doc_obj):
        doc_obj, doc = self._save(doc_obj)
        self._s3.Object(self.bucket, doc_obj._id).put(
            Body=json.dumps(doc))
        pipe = self._redis.pipeline()
        pipe = self.add_to_model_set(doc_obj, pipe)
        pipe = self.add_indexes(doc_obj, doc, pipe)
        pipe = self.remove_indexes(doc_obj, pipe)
        pipe.execute()
        doc_obj._doc = doc_obj.process_doc_kwargs(doc)
        return doc_obj

    def get(self,doc_obj,doc_id):
        doc = json.loads(self._s3.Object(
            self.bucket, doc_obj.get_doc_id(doc_id)).get().get('Body').read())

        return doc_obj.__class__(**doc)

    def flush_db(self):
        self._redis.flushdb()
        obj_list = list(self._s3.Bucket(self.bucket).objects.all())
        for i in obj_list:
            i.delete()

    def delete(self, doc_obj):
        self._s3.Object(self.bucket,doc_obj._id).delete()
        pipe = self._redis.pipeline()
        pipe = self.remove_from_model_set(doc_obj, pipe)
        doc_obj._index_change_list = doc_obj.get_indexes()
        pipe = self.remove_indexes(doc_obj, pipe)
        pipe.execute()

    def all(self,cls):
        klass = cls()
        id_list = [id.rsplit(':',1)[1] for id in self._redis.smembers('{0}:all'.format(
            klass.get_class_name()))]
        obj_list = []

        for id in id_list:
            obj_list.append(self.get(klass,id))
        return obj_list

    def evaluate(self, filters_list, doc_class):
        if len(filters_list) == 1:
            id_list = self._redis.smembers(filters_list[0])
        else:
            id_list = self._redis.sinter(*filters_list)
        return [doc_class.get(self.parse_id(id)) for id in id_list]