#!/usr/bin/env bash

: ' Rotate passwords for the apps

    # exit(s) status code(s)
    0 - success
    1 - fail
    '

# check if debug flag is set
if [ "${DEBUG}" = true ]; then

  set -x # enable print commands and their arguments as they are executed.
  export # show all declared variables (includes system variables)
  whoami # print current user

else

  # unset if flag is not set
  unset DEBUG

fi

# bash default parameters
set -o errexit  # make your script exit when a command fails
set -o pipefail # exit status of the last command that threw a non-zero exit code is returned
set -o nounset  # exit when your script tries to use undeclared variables

# check binaries
which jq
which xmlstarlet

# functions
function servarr_read_api_key() {
  local __app_name=$1
  xmlstarlet sel --template --value-of '//ApiKey' "../configs/${__app_name}/config/config.xml"
}

function servarr_read_config() {
  local __app_name=$1
  local __app_api_key=$2
  local __app_api_version=${3-"1"}

  curl \
    "https://127.0.0.1/${__app_name}/api/v${__app_api_version}/config/host" \
    --silent \
    --insecure \
    --request "GET" \
    --header "X-Api-Key: ${__app_api_key}" \
    >/tmp/${__app_name}-response.json
}

function servarr_change_json_password() {
  local __app_name=$1
  local __password=$2
  jq '.password = "${__password}" | .passwordConfirmation = "${__password}"' "/tmp/${__app_name}-response.json" >"/tmp/${__app_name}-request.json"
}

function servarr_change_password() {
  local __app_name=$1
  local __app_api_key=$2
  local __app_api_version=${3-"1"}
  curl \
    "https://127.0.0.1/${__app_name}/api/v${__app_api_version}/config/host" \
    --silent \
    --insecure \
    --request "PUT" \
    --header "X-Api-Key: ${__app_api_key}" \
    --header 'Content-Type: application/json' \
    --data @"/tmp/${__app_name}-request.json"
}

function servarr_validate_login() {
  local __app_name=$1
  local __password=$2

  curl \
    "https://127.0.0.1/${__app_name}/login" \
    --silent \
    --insecure \
    --request "POST" \
    --header 'Content-Type: multipart/form-data' \
    --form username=${__app_name} \
    --form password=${__password}
}

readonly __lidar_api_key__=$(servarr_read_api_key lidarr)
servarr_read_config lidarr ${__lidar_api_key__}
servarr_change_json_password lidarr lidarr
servarr_change_password lidarr ${__lidar_api_key__} lidarr
servarr_validate_login lidarr lidarr

# # read the API key
# readonly __lidarr_api_key__=$(xmlstarlet sel -t -v "//ApiKey" -nl "../configs/lidarr/config/config.xml")

# # get the host info
# curl 'https://127.0.0.1/lidarr/api/v1/config/host' \
#   -X 'GET' \
#   -H "X-Api-Key: ${__lidarr_api_key__}" \
#   --insecure \
#   > /tmp/lidarr-response.json

# # update the password
# jq '.username = "lidarr" | .password = "lidarr" | .passwordConfirmation = "lidarr"' /tmp/lidarr-response.json > /tmp/lidarr-request.json

# # change the password
# curl 'https://127.0.0.1/lidarr/api/v1/config/host' \
#   -X 'PUT' \
#   -H 'Content-Type: application/json' \
#   -H "X-Api-Key: ${__lidarr_api_key__}" \
#   --insecure \
#   --data @/tmp/lidarr-request.json

# # validate the password
