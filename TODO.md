## TODOS

Focus only on linux for now just polish things and make linux usable first

Tools
1. Organize tools by category 
2. connect tools to api
3. single adapter pattern to register all of the tools as well to access 

DB
1. create schema for admin, computer, workspaces, apps, permissions, network_permissions, file_permissions, command_permissions, runs 
2. andd crud routes for all of these
3. Backups

Docker
1. lifecycle methods for creatig, pausing, destryong, the containers
2. sync the status to db 
3. monetring serice to montir all of the docker containers running
4. allow users to spin snadboxes on another machines as well on same network as well some other network 

API
1. auth api
2. admins api
3. computers api 
4. monetring api

UI
1. build dashboards
2. move to tanstack start instaed of react version

PACKAGE
1. a pythong package for cua agents 
2. a package for normal agents as well


MISC
1. allow usrs to connect domains to there dashboards 
2. rerouting and also certifiates 
3. spin up clusters on multiple machines as well 
4. file system backups as well 
5. open terlemetry for tracing all requests, tool calls, db queries
6. logs with grafana
7. sync data to another machines as well 
8. secrete manager and allowig users to embed profiles in the appliatons in these containers as well
9. add support for just code execution sandboxes, browser tools 