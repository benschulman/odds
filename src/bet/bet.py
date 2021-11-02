import pandas as pd
import sys
from bs4 import BeautifulSoup
import requests
import logging
from datetime import datetime
from util import static_vars
from typing import OrderedDict

from emailme import construct_email_from_template, send_email, df_to_dct

import os

NFL_ODDS_URL_LINE = 'https://www.sportsline.com/nfl/odds/money-line/'
NFL_ODDS_URL_SPREAD = 'https://www.sportsline.com/nfl/odds/picks-against-the-spread/'

@static_vars(counter=0)
def _extract_single_game(game, spread=False):
    _extract_single_game.counter += 1
    
    table_rows = game.find_all('tr')
    # table_rows[0] empty
    # table_rows[1] away team
    # table_rows[2] home team
    # table_rows[3] date
    # table_rows[4] empty
    if len(table_rows) != 5:
        logging.warning(f'Found more rows in {_extract_single_game.counter}th game than expected')
        logging.warning(f'found {len(table_rows)} rows')
    
    # Game data will hold the odds data for a single game
    game_data = []
    
    away = table_rows[1].find_all('td')
    home = table_rows[2].find_all('td')
    
    if len(home) != len(away):
        logging.warning(f'The length of the home data is not equal to the length of the away data')
        logging.warning(f'Home: {len(home)} Away: {len(away)}')
        
    if len(home) != 7:
        logging.warning(f'Home array on {_extract_single_game.counter}th game is {len(home)} should be 7')
        
    if len(away) != 7:
        logging.warning(f'Home array on {_extract_single_game.counter}th game is {len(away)} should be 7')
    
    
    for i, (away_data, home_data) in enumerate(zip(away, home)):
        # Name and Record are found in the same td entry
        if i == 0:
            # Extract Names
            name_a = away_data.find('h4').text
            name_h = home_data.find('h4').text
            
            # Extract Records
            rec_a = away_data.find('span').text
            rec_h = home_data.find('span').text
            
            game_data.append((name_a, name_h))
            game_data.append((rec_a, rec_h))
        # Projected Score case
        elif i == 1:
            game_data.append('')
        else:
            away_odds_html = away_data.find(class_='current-value')
            home_odds_html = home_data.find(class_='current-value')
            
            if away_odds_html is None or home_odds_html is None:
                logging.info(f'No odds found for game {_extract_single_game.counter} at column {i}')
                # No odds
                game_data.append(('', ''))
                # No Open odds
                game_data.append(('', ''))
                continue
            
            if spread:
                away_spread = away_odds_html.find(class_='primary').text
                away_at = away_odds_html.find(class_='secondary').text
                
                home_spread = home_odds_html.find(class_='primary').text
                home_at = home_odds_html.find(class_='secondary').text
                
                game_data.append((f"{away_spread} @ {away_at}", f"{home_spread} @ {home_at}"))
            else:
                game_data.append((away_odds_html.text, home_odds_html.text))
            
            # The i == 1 case is a "locked" field for Proj Score
            # All other cases are odds and will have an "open" field

            open_a = away_data.find_all('div')[-1].text.split(': ')
            open_h = home_data.find_all('div')[-1].text.split(': ')

            if open_a[0].lower().strip() != 'open' or open_h[0].lower().strip() != 'open':
                logging.warning(f'Did not find "Open" field for game {_extract_single_game.counter} for away team')
                game_data.append(('', ''))
                continue


            game_data.append((open_a[1], open_h[1]))
    
    # Date and Chanel
    date, _ = table_rows[3].find_all('div')[-1].text.split(' on ')
    game_data.append(date)
    
    logging.debug(f'Data for game {_extract_single_game.counter}: {game_data}')
    
    return game_data

def retrieve_game_lines_table(spread=False):
    url = None

    if spread:
        url = NFL_ODDS_URL_SPREAD
    else:
        url = NFL_ODDS_URL_LINE
    
    html = requests.get(url)
    
    if html.status_code != 200:
        logging.error(f'URL: {url} returned status {html.status_code}')
        raise Exception
    
    soup = BeautifulSoup(html.text, 'lxml')
    
    
    table = soup.find("table")
    
    # the header of the table containing all of the column labels
    table_head = table.find('thead')
    
    headers = table_head.find_all('th')
    
    # retrieve the columns from headers
    cols = []
    for x in headers:
        # Caesers is a jpg so there is no text
        if x.text == '':
            cols.append("caesers")
        else:
            cols.append(x.text)
        
        # Add the open field to the tables
        if x.text in ['consensus','','draftkings','fanduel','westgate']:
            if x.text == '':
                cols.append('caesers_open')
            else:
                cols.append(x.text + '_open')
    
    cols.insert(1, 'record')
    cols.append('date')

    if spread:
        cols2 = []
        for col in cols:
            col += '_spread'
            cols2.append(col)
        cols = cols2

    logging.info(f'Columns: {cols}')
    print(cols)
    
    # game_tables will be a list where each element represents a single game's html
    games_tables = table.find_all('tbody')
    logging.info(f'Found {len(games_tables)} games')
    
    logging.info('Begin Parsing Game Data')
    # Data will hold the data for every game
    # Format: [[(`away`, `home`), (`record_away`, `record_home`), ('', ''),
    #           (`line1_away`, `line1_away`), (`line1_away_open`, `line1_home_open`),..., date],
    #            ...]
    data = []
    for game in games_tables:
        data.append(_extract_single_game(game, spread=spread))
    
    logging.info('Finished Parsing Game Data')
    
    df = pd.DataFrame(data, columns=cols)
    if spread:
        df.drop(['Proj Score_spread'], axis=1, inplace=True)
    else:
        df.drop(['Proj Score'], axis=1, inplace=True)
    
    return df

def run():
    logging.basicConfig(filename='odds.log', level=logging.INFO)
    
    today = datetime.now()
    todays_date = today.strftime("%m_%d_%Y_%H_%M")

    df1 = retrieve_game_lines_table()
    df2 = retrieve_game_lines_table(spread=True)

    df2['Matchup'] = df2['Matchup_spread']
    df2.drop(['date_spread', 'record_spread', 'Matchup_spread'], axis=1, inplace=True)
    

    df = pd.merge(df1, df2, on='Matchup')

    data_path = os.environ['ODDS_PATH']
    
    df_tosend = df[["Matchup", "record", "fanduel", "fanduel_open", 'fanduel_spread', 'fanduel_open_spread']]
    dct = df_to_dct(df_tosend)

    args = OrderedDict()
    args["intro"] = "Here is your sports update!"
    #args["body"] = "Here is your update"
    #args["conclusion"] = "Goodbye"

    msg = construct_email_from_template(
        args, "template.html", os.environ['EMAIL'], subject="NFL", table=dct
    )

    to = sys.argv[1]
    send_email(to, msg)

    df.to_csv(f'{data_path}/data/odds_{todays_date}.tsv', sep='\t', index=False)

if __name__ == '__main__':
    run()
