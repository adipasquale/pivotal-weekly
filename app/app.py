from flask import Flask, render_template, redirect, url_for
import requests
import dateutil.parser
import datetime
import pytz
import gevent
from gevent import monkey
from collections import defaultdict
import os
monkey.patch_all()

app = Flask(__name__)


API_ROOT_URL = "https://www.pivotaltracker.com/services/v5/projects/%s" % os.environ["PROJECT_ID"]
API_TOKEN = os.environ["API_TOKEN"]


def init_stories_struct():
    return {"previous_week": [], "next_week": [], "days": [[] for i in range(0, 7)]}


class PivotalWeek(object):

  def __init__(self, year, week, is_current_week):
    self.is_current_week = is_current_week

    self.USERS = None
    self.USER_NAMES = {}

    self.TODAY = datetime.datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = pytz.utc.localize(datetime.datetime.strptime("%s-%s-0-UTC" % (year, week), "%Y-%W-%w-%Z"))
    self.DATES = [monday + datetime.timedelta(days=i) for i in range(0, 7)]
    self.DAY_NAMES = [date.strftime("%A<br/>%d") for date in self.DATES]

  def api_request(self, path, params=None):
    kwargs = {"headers": {"X-TrackerToken": API_TOKEN}}
    if params:
      kwargs["params"] = params
    res = requests.get(API_ROOT_URL + "/" + path, **kwargs)
    return res.json()

  def get_started_day_idx(self, story):
    if story["started_at"] < self.DATES[0]:
      return "previous_week"
    for i, date in enumerate(self.DATES[1:]):
      if story["started_at"] < date:
        return i

  def get_start_date_for_story(self, story):
    activity_list = self.api_request("/stories/%s/activity" % story["id"])
    found_date = story.get("accepted_at")  # default to this
    for activity in activity_list:
      for change in activity["changes"]:
        if change["change_type"] == "update"\
           and "current_state" in change["original_values"]\
           and "current_state" in change["new_values"]\
           and change["original_values"]["current_state"] != "started"\
           and change["new_values"]["current_state"] == "started":
          found_date = change["new_values"]["updated_at"]
          break
    story["started_at"] = dateutil.parser.parse(found_date)

    if story["current_state"] == "started":
      story["span_days"] = (self.TODAY - story["started_at"]).days
    elif story["current_state"] == "accepted":
      story["span_days"] = (self.TODAY - story["started_at"]).days

  def augment_stories(self):
    jobs = [gevent.spawn(self.get_start_date_for_story, story) for story in self.stories]
    gevent.joinall(jobs, timeout=100000)

  def organize_stories(self):
    stories_organized = defaultdict(dict)
    for user_id in [user["person"]["id"] for user in self.USERS]:
      stories_organized[user_id] = init_stories_struct()
    for story in self.stories:
      started_day = self.get_started_day_idx(story)
      if isinstance(started_day, int):
        for owner_id in story["owner_ids"]:
          stories_organized[owner_id]["days"][started_day].append(story)
      else:  # previous and next week
        for owner_id in story["owner_ids"]:
          stories_organized[owner_id][started_day].append(story)
    self.stories = stories_organized

  def fetch_users(self):
    self.USERS = self.api_request("memberships")
    for user in self.USERS:
      self.USER_NAMES[user["person"]["id"]] = user["person"]["name"].split(" ")[0].lower()

  def fetch_stories(self):
    # fetch all currently started stories OR accepted this week
    monday = self.DATES[0].strftime("%m/%d/%Y")
    friday = self.DATES[-1].strftime("%m/%d/%Y")
    query = "accepted:%s..%s OR started:%s..%s" % (monday, friday, monday, friday)
    if self.is_current_week:
      query += " OR state:started"

    print "query is %s" % query
    self.stories = self.api_request("search", params={"query": query})["stories"]["stories"]

    self.augment_stories()
    self.organize_stories()


@app.route('/<int:year>/<int:week>')
def show_week(year, week):
  today = datetime.date.today()
  is_current_week = (today.year == year and today.isocalendar()[1] == week)

  api_caller = PivotalWeek(year, week, is_current_week)

  api_caller.fetch_users()
  api_caller.fetch_stories()

  return render_template('week.html',
                         stories=api_caller.stories,
                         days=api_caller.DAY_NAMES,
                         users=api_caller.USER_NAMES,
                         render_template=render_template)


@app.route('/')
def home():
  today = datetime.date.today()
  return redirect(url_for('show_week', year=today.year, week=today.isocalendar()[1]))

if __name__ == '__main__':

  app.run(debug=("DEBUG" in os.environ), port=int(os.environ.get("PORT", 5000)))

  # PROJECT_ID=764125 API_TOKEN=e66cf99aab8b9d69134344399d4eec1f python app/app.py
