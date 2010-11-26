# coding: utf-8
"""
"""
import bnw_objects as objs
from base import genid,cropstring
from twisted.internet import interfaces, defer, reactor
import time
from twisted.python import log

listeners={}

@defer.inlineCallbacks
def subscribe(user,target_type,target,fast=False,sfrom=None):
    """!Подписка пользователя на что-нибудь.
    @param user Объект-пользователь.
    @param target_type Тип цели - user,tag,club.
    @param target Цель подписки.
    @param fast Если равно true, не проверяем существование подписки."""
    sub_rec={ 'user': user['name'], 'target': target, 'type': target_type }
    if fast or ((yield objs.Subscription.find_one(sub_rec)) is None):
        sub=objs.Subscription(sub_rec)
        sub['jid']=user['jid']
        if sfrom:
            sub['from']=sfrom
        if target_type=='sub_user':
            tuser=yield objs.User.find_one({'name':target})
            if not tuser:
                defer.returnValue('No such user.')
            _ = yield tuser.send_plain('@%s subscribed to your blog. http://bnw.blasux.ru/u/%s' % (user['name'],user['name']))
            pass
        if (yield sub.save()):
            defer.returnValue('Subscribed.')
        else:
            defer.returnValue('Error while saving.')
    else:
        defer.returnValue('Already subscribed.')

@defer.inlineCallbacks
def unsubscribe(user,target_type,target,fast=False):
    """!Отписка пользователя от чего-нибудь.
    @param user Объект-пользователь.
    @param target_type Тип цели - user,tag,club.
    @param target Цель подписки.
    @param fast Игнорируется."""
    sub_rec={ 'user': user['name'], 'target': target, 'type': target_type }
    rest = yield objs.Subscription.remove(sub_rec)
    defer.returnValue(rest)

@defer.inlineCallbacks
def send_to_subscribers(queries,is_message,message,recommender=None):
    """!Это дерьмо рассылает сообщение или коммент подписчикам.
    @param queries Список запросов, по которым можно найти подписки.
    @param is_message Является ли сообщением. Если нет - коммент.
    @param message Собственно сообщение или коммент.
    @todo Что-то как-то уныло и негибко.
    """
    recipients=set()
    qn=0
    for query in queries:
        qn+=1
        for result in (yield objs.Subscription.find(query,fields=['user'])):
            recipients.add(result['user'])
    for target_name in recipients:
        target=yield objs.User.find_one({'name': target_name},fields=['jid','off','interface'])
        qn+=1
        if target:
            if not target.get('off',False):
                if is_message:
                    feedel_val = {'user': target_name,'message':message['id']}
                    feedel = yield objs.FeedElement.find_one(feedel_val)
                    if not feedel:
                        feedel = objs.FeedElement(feedel_val)
                        target.send_post(message,recommender)
                        _ = yield feedel.save()
                else:
                    target.send_comment(message)
                log.msg('Sent %s to %s' % (message['id'],target['jid']))
    defer.returnValue((qn,len(recipients)))

@defer.inlineCallbacks
def postMessage(user,tags,clubs,text,anon=False,anoncom=False):
    """!Это дерьмо создает новое сообщение и рассылает его.
    @param user Объект-пользователь.
    @param tags Список тегов.
    @param clubs Список клубов.
    @param text Текст сообщения.
    @param anon Отправить от анона.
    @param anoncom Все комментарии принудительно анонимны.
    """
    if len(text)==0:
        defer.returnValue('So where is your post?')
    if len(text)>2048:
        #defer.returnValue('E_LONG')
        #XmppResponse('Message is too long. %d/2048' % (len(text),))
        defer.returnValue('Message is too long. %d/2048' % (len(text),))
    message={ 'user': user['name'],
              'tags': tags,
              'clubs': clubs,
              'id': genid(6),
              'date': time.time(),
              'replycount': 0,
              'text': text,
              'anonymous': anon,
              'anoncomments': anoncom,
            }
    if anon:
        message['real_user']=message['user']
        message['user']='anonymous'
    stored_message = objs.Message(message)
    stored_message_id = yield stored_message.save()
    
    sub_result = yield subscribe(user,'sub_message',message['id'],True)
    
    queries=[{'target': tag, 'type': 'sub_tag'} for tag in tags]
    queries+=[{'target': club, 'type': 'sub_club'} for club in clubs]
    queries+=[{'target': 'anonymous' if anon else user['name'], 'type': 'sub_user'}]
    qn,recipients = yield send_to_subscribers(queries,True,message)
    defer.returnValue((message['id'],qn,recipients))
    #defer.returnValue('Posted with id %s and delivered to %d users. Total cost: $%d' % (message['id'].upper(),recipients,qn))

@defer.inlineCallbacks
def postComment(message_id,comment_id,text,user,anon=False):
    """!Это дерьмо постит комментарий.
    @param message_id Id сообщения к которому комментарий.
    @param comment_id Если ответ - id комментария, на который отвечаем.
    @param text Текст комментария.
    @param user Объект-пользователь.
    @param anon Анонимный ответ.
    """

    if len(text)==0:
        defer.returnValue('So where is your comment?')
    if len(text)>2048:
        defer.returnValue('Comment is too long. %d/2048' % (len(text),))
    message=yield objs.Message.find_one({'id': message_id})
    if comment_id!=None:
        old_comment=yield objs.Comment.find_one({'id': message_id+'/'+comment_id, 'message': message_id})
    else:
        old_comment=None
    if old_comment==None and comment_id!=None:
        defer.returnValue('No such comment.')
    if message==None:
        defer.returnValue('No such message.')
    
    comment={ 'user': user['name'],
              'id': message_id+'/'+genid(3),
              'message': message_id,
              'date': time.time(),
              'replyto': old_comment['id'] if old_comment else None,
              'num': message['replycount']+1,
              'replytotext': cropstring(old_comment['text'] if comment_id else message['text'],128),
              'text': ('@'+old_comment['user']+' 'if comment_id else '')+text,
              'anonymous': anon,
            }
    if anon:
        comment['real_user']=comment['user']
        comment['user']='anonymous'
    comment = objs.Comment(comment)
    comment_id = yield comment.save()
    sub_result = yield subscribe(user,'sub_message',message_id)
    _ = (yield objs.Message.mupdate({'id':message_id},{'$inc': { 'replycount': 1}}))
    
    qn,recipients = yield send_to_subscribers([{'target': message_id, 'type': 'sub_message'}],False,comment)
    publish('comments-'+message_id,comment.filter_fields()) # ALARM
    defer.returnValue((comment['id'],qn,recipients))
    defer.returnValue('Posted with id %s and delivered to %d users. Total cost: $%d' % (message['id'].upper(),recipients,qn))

listenerscount=0
def register_listener(etype,name,handler):
    global listeners
    global listenerscount
    listenerscount+=1
    if not (etype in listeners):
        listeners[etype]={}
    listeners[etype][name]=handler

def unregister_listener(etype,name):
    global listeners
    global listenerscount
    listenerscount-=1
    del listeners[etype][name]
    if not listeners[etype]:
        del listeners[etype]

def publish(etype,*args,**kwargs):
    global listeners
    for rtype in (etype,None):
        if rtype in listeners:
            for listener in listeners[rtype].itervalues():
                listener(*args,**kwargs)

        