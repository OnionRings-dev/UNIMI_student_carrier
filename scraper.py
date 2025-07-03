import requests
from bs4 import BeautifulSoup
import json
import time
import re
from urllib.parse import urljoin, urlparse
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UNIMIScraper:
    def __init__(self):
        self.base_url = "https://www.unimi.it"
        self.courses_url = "https://www.unimi.it/it/corsi/corsi-di-laurea-triennali-e-magistrali-ciclo-unico"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.courses_data = []
        
    def get_page_content(self, url):
        """Fetch page content with error handling"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def extract_total_cfu(self, soup):
        """Extract total CFU from course page"""
        # Look for patterns like "180 Crediti"
        text = soup.get_text()
        cfu_match = re.search(r'(\d+)\s+Crediti', text)
        if cfu_match:
            return int(cfu_match.group(1))
        return None
    
    def parse_course_structure(self, soup):
        """Parse the course structure from the course page"""
        course_structure = {
            'years': [],
            'total_cfu': self.extract_total_cfu(soup),
            'total_obligatory_exams': 0,
            'total_optional_exams': 0,
            'total_obligatory_cfu': 0,
            'total_optional_cfu': 0
        }
        
        # Find all year tabs
        year_tabs = soup.find_all('div', class_='tab-pane')
        
        for year_tab in year_tabs:
            year_id = year_tab.get('id', '')
            year_match = re.search(r'year-af-.*-(\d+)', year_id)
            if not year_match:
                continue
                
            year_number = int(year_match.group(1)) + 1  # 0-indexed to 1-indexed
            
            year_data = {
                'year': year_number,
                'semesters': []
            }
            
            # Find semesters within this year
            semester_sections = year_tab.find_all('div', class_='titoletto')
            
            current_semester = None
            
            for element in year_tab.find_all(['div', 'table']):
                if element.name == 'div' and 'titoletto' in element.get('class', []):
                    # New semester
                    semester_text = element.get_text().strip()
                    if 'primo semestre' in semester_text.lower():
                        current_semester = 1
                    elif 'secondo semestre' in semester_text.lower():
                        current_semester = 2
                    elif 'annuale' in semester_text.lower():
                        current_semester = 'annual'
                    else:
                        current_semester = 'unknown'
                    
                    # Add semester data structure
                    semester_data = {
                        'semester': current_semester,
                        'obligatory_exams': [],
                        'optional_exams': []
                    }
                    year_data['semesters'].append(semester_data)
                
                elif element.name == 'table' and current_semester is not None:
                    # Parse exams table
                    if year_data['semesters']:
                        self.parse_exams_table(element, year_data['semesters'][-1], course_structure)
            
            if year_data['semesters']:
                course_structure['years'].append(year_data)
        
        return course_structure
    
    def parse_exams_table(self, table, semester_data, course_structure):
        """Parse exams from a table"""
        current_section = None
        
        tbody = table.find('tbody')
        if not tbody:
            return
            
        for row in tbody.find_all('tr'):
            # Check if this is a section header (Obbligatorio/A scelta)
            if 'rowsubtitle' in row.get('class', []):
                section_text = row.get_text().strip().lower()
                if 'obbligatorio' in section_text:
                    current_section = 'obligatory'
                elif 'scelta' in section_text or 'opzional' in section_text:
                    current_section = 'optional'
                continue
            
            # Parse exam row
            cells = row.find_all('td')
            if len(cells) >= 5:
                exam_data = self.parse_exam_row(cells)
                if exam_data:
                    if current_section == 'obligatory':
                        semester_data['obligatory_exams'].append(exam_data)
                        course_structure['total_obligatory_exams'] += 1
                        course_structure['total_obligatory_cfu'] += exam_data['cfu']
                    elif current_section == 'optional':
                        semester_data['optional_exams'].append(exam_data)
                        course_structure['total_optional_exams'] += 1
                        course_structure['total_optional_cfu'] += exam_data['cfu']
    
    def parse_exam_row(self, cells):
        """Parse a single exam row"""
        try:
            name_cell = cells[0]
            cfu_cell = cells[1]
            hours_cell = cells[2]
            language_cell = cells[3]
            ssd_cell = cells[4]
            
            # Extract exam name and link
            name_link = name_cell.find('a')
            if name_link:
                name = name_link.get_text().strip()
                link = urljoin(self.base_url, name_link.get('href', ''))
            else:
                name = name_cell.get_text().strip()
                link = None
            
            # Extract CFU
            cfu_text = cfu_cell.get_text().strip()
            cfu_match = re.search(r'(\d+)', cfu_text)
            cfu = int(cfu_match.group(1)) if cfu_match else 0
            
            # Extract hours
            hours_text = hours_cell.get_text().strip()
            hours_match = re.search(r'(\d+)', hours_text)
            hours = int(hours_match.group(1)) if hours_match else 0
            
            return {
                'name': name,
                'cfu': cfu,
                'hours': hours,
                'language': language_cell.get_text().strip(),
                'ssd': ssd_cell.get_text().strip(),
                'link': link
            }
        except Exception as e:
            logger.error(f"Error parsing exam row: {e}")
            return None
    
    def get_course_links(self):
        """Get all course links from the main page"""
        logger.info("Fetching course links from main page...")
        
        content = self.get_page_content(self.courses_url)
        if not content:
            return []
        
        soup = BeautifulSoup(content, 'html.parser')
        course_links = []
        
        # Find all course links
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if href and '/it/corsi/' in href and 'laurea' in href.lower():
                full_url = urljoin(self.base_url, href)
                course_title = link.get_text().strip()
                if course_title and len(course_title) > 5:  # Filter out short/empty links
                    course_links.append({
                        'title': course_title,
                        'url': full_url
                    })
        
        # Remove duplicates
        unique_courses = []
        seen_urls = set()
        for course in course_links:
            if course['url'] not in seen_urls:
                unique_courses.append(course)
                seen_urls.add(course['url'])
        
        logger.info(f"Found {len(unique_courses)} unique courses")
        return unique_courses
    
    def scrape_course_details(self, course_info):
        """Scrape detailed information for a single course"""
        logger.info(f"Scraping course: {course_info['title']}")
        
        content = self.get_page_content(course_info['url'])
        if not content:
            return None
        
        soup = BeautifulSoup(content, 'html.parser')
        
        # Parse course structure
        course_structure = self.parse_course_structure(soup)
        
        # Extract additional course information
        course_data = {
            'title': course_info['title'],
            'url': course_info['url'],
            'total_cfu': course_structure['total_cfu'],
            'total_obligatory_exams': course_structure['total_obligatory_exams'],
            'total_optional_exams': course_structure['total_optional_exams'],
            'total_obligatory_cfu': course_structure['total_obligatory_cfu'],
            'total_optional_cfu': course_structure['total_optional_cfu'],
            'years': course_structure['years']
        }
        
        return course_data
    
    def scrape_all_courses(self, max_courses=None):
        """Scrape all courses from UNIMI"""
        logger.info("Starting UNIMI courses scraping...")
        
        # Get all course links
        course_links = self.get_course_links()
        
        if max_courses:
            course_links = course_links[:max_courses]
        
        # Scrape each course
        for i, course_info in enumerate(course_links, 1):
            logger.info(f"Processing course {i}/{len(course_links)}: {course_info['title']}")
            
            course_data = self.scrape_course_details(course_info)
            if course_data:
                self.courses_data.append(course_data)
            
            # Be respectful with delays
            time.sleep(1)
        
        logger.info(f"Scraping completed. Total courses scraped: {len(self.courses_data)}")
        return self.courses_data
    
    def save_to_json(self, filename='unimi_courses.json'):
        """Save scraped data to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.courses_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Data saved to {filename}")
    
    def get_summary_stats(self):
        """Get summary statistics of scraped data"""
        if not self.courses_data:
            return "No data available"
        
        total_courses = len(self.courses_data)
        total_exams = sum(course['total_obligatory_exams'] + course['total_optional_exams'] 
                         for course in self.courses_data)
        total_cfu = sum(course['total_cfu'] for course in self.courses_data if course['total_cfu'])
        
        return {
            'total_courses': total_courses,
            'total_exams': total_exams,
            'average_cfu_per_course': total_cfu / total_courses if total_courses > 0 else 0,
            'courses_with_structure': len([c for c in self.courses_data if c['years']])
        }

# Usage example
if __name__ == "__main__":
    scraper = UNIMIScraper()
    
    # For testing, limit to first 5 courses
    # Remove max_courses parameter to scrape all courses
    data = scraper.scrape_all_courses()
    
    # Save to JSON
    scraper.save_to_json('unimi_courses.json')
    
    # Print summary
    stats = scraper.get_summary_stats()
    print("\nScraping Summary:")
    print(f"Total courses: {stats['total_courses']}")
    print(f"Total exams: {stats['total_exams']}")
    print(f"Average CFU per course: {stats['average_cfu_per_course']:.1f}")
    print(f"Courses with detailed structure: {stats['courses_with_structure']}")
    
    # Print example course structure
    if data:
        print("\nExample course structure:")
        print(json.dumps(data[0], indent=2, ensure_ascii=False))